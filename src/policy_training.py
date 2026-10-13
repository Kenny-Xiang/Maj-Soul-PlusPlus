"""Offline supervised training; PyTorch is never imported by the desktop runtime."""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from policy_actions import ACTION_SCHEMA_VERSION, action_key, legal_actions
from policy_features import (FEATURE_SIGNATURE, FEATURE_VERSION, RULESET, ACTIONS,
                             PLANE_NAMES, GLOBAL_NAMES, ACTION_NAMES, encode_state, encode_actions)
from policy_model import MODEL_FORMAT, weight_shapes


class ResidualBlock(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.conv1 = nn.Conv1d(channels, channels, 3, padding=1)
        self.conv2 = nn.Conv1d(channels, channels, 3, padding=1)

    def forward(self, x):
        return torch.relu(x + self.conv2(torch.relu(self.conv1(x))))


class CandidatePolicy(nn.Module):
    def __init__(self, config):
        super().__init__()
        weight_shapes(config)
        self.config = dict(config)
        channels, hidden = config["channels"], config["hidden"]
        self.conv = nn.Conv1d(len(PLANE_NAMES), channels, 3, padding=1)
        self.blocks = nn.Sequential(*(ResidualBlock(channels) for _ in range(config["blocks"])))
        self.state = nn.Linear(channels * 34 + len(GLOBAL_NAMES), hidden)
        self.score = nn.Sequential(nn.Linear(hidden + len(ACTION_NAMES), hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, planes, globals_, actions, mask):
        encoded = self.blocks(torch.relu(self.conv(planes))).flatten(1)
        encoded = torch.relu(self.state(torch.cat((encoded, globals_), dim=1)))
        # The state part is identical for every candidate; multiply it once.
        first = self.score[0]
        hidden = encoded.shape[1]
        state_score = nn.functional.linear(encoded, first.weight[:, :hidden], first.bias)
        action_score = nn.functional.linear(actions, first.weight[:, hidden:])
        logits = self.score[2](torch.relu(state_score[:, None, :] + action_score)).squeeze(-1)
        return logits.masked_fill(~mask, -torch.inf)


def read_samples(paths, players):
    """Reject malformed labels; never repair a label by adding it to the mask."""
    samples, seen, duplicates, sources = [], {}, 0, []
    for path in map(Path, paths):
        payload = path.read_bytes()
        sources.append({"file": path.name, "sha256": hashlib.sha256(payload).hexdigest()})
        if path.name.endswith(".jsonl.zst"):
            try:
                import zstandard
            except ImportError as exc:
                raise ImportError("Reading .jsonl.zst samples requires the optional zstandard package") from exc
            handle = zstandard.open(io.BytesIO(payload), "rt", encoding="utf-8")
        else:
            handle = io.StringIO(payload.decode("utf-8"))
        with handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                    if sample.get("schemaVersion") != 1 or sample.get("ruleset") != RULESET:
                        raise ValueError("unsupported sample schema/ruleset")
                    if sample["state"]["playerCount"] != players:
                        continue
                    if sample.get("labelSource") not in ("explicit", "accepted", "inferred_pass"):
                        raise ValueError("uncertain action label is not trainable")
                    identity = (sample["gameId"], str(sample["roundId"]), str(sample["decisionId"]), sample["seat"])
                    if not isinstance(identity[0], str) or not identity[0]:
                        raise ValueError("missing game identity")
                    if sample["seat"] != sample["state"]["selfSeat"]:
                        raise ValueError("sample seat differs from visible-state owner")
                    fingerprint = hashlib.sha256(json.dumps(sample, sort_keys=True).encode()).hexdigest()
                    if identity in seen:
                        if seen[identity] != fingerprint:
                            raise ValueError("conflicting duplicate decision")
                        duplicates += 1
                        continue
                    seen[identity] = fingerprint
                    candidates = legal_actions(sample["state"])
                    keys = [candidate["actionId"] for candidate in candidates]
                    label = action_key(sample["action"])
                    if label not in keys:
                        raise ValueError("observed action is not in the complete legal candidate set")
                    planes, scalars = encode_state(sample["state"])
                    samples.append({"game": sample["gameId"], "planes": planes, "globals": scalars,
                                    "actions": encode_actions(sample["state"], candidates),
                                    "target": keys.index(label), "action": sample["action"]["action"],
                                    "labelSource": sample["labelSource"]})
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    raise ValueError(f"{path.name}:{line_number}: {exc}") from exc
    if not samples:
        raise ValueError("no trainable samples for the requested player count")
    return samples, {"inputs": sources, "duplicateSamples": duplicates,
                     "samples": len(samples), "games": len({s["game"] for s in samples}),
                     "actions": dict(Counter(s["action"] for s in samples)),
                     "labelSources": dict(Counter(s["labelSource"] for s in samples))}


def split_games(samples, seed, smoke=False):
    games = sorted({sample["game"] for sample in samples},
                   key=lambda game: hashlib.sha256(f"{seed}:{game}".encode()).digest())
    if not smoke and len(games) < 3:
        raise ValueError("training needs at least three distinct games for disjoint train/validation/test; use --smoke for a pipeline check")
    if smoke:
        groups = {"train": games, "validation": [], "test": []}
    else:
        held = max(1, len(games) // 10)
        groups = {"train": games[held * 2:], "validation": games[:held], "test": games[held:held * 2]}
    lookup = {game: name for name, group in groups.items() for game in group}
    result = {name: [] for name in groups}
    for sample in samples:
        result[lookup[sample["game"]]].append(sample)
    return result, groups


def batch_tensors(samples, device):
    count = max(len(s["actions"]) for s in samples)
    actions = np.zeros((len(samples), count, len(ACTION_NAMES)), dtype=np.float32)
    mask = np.zeros((len(samples), count), dtype=bool)
    for i, sample in enumerate(samples):
        length = len(sample["actions"])
        actions[i, :length], mask[i, :length] = sample["actions"], True
    return tuple(torch.as_tensor(value, device=device) for value in (
        np.stack([s["planes"] for s in samples]), np.stack([s["globals"] for s in samples]),
        actions, mask, np.asarray([s["target"] for s in samples], dtype=np.int64)))


@torch.no_grad()
def evaluate(model, samples, device, batch_size):
    if not samples:
        return None
    model.eval()
    totals = {"samples": len(samples), "choices": 0, "forced": 0,
              "choiceTop1": 0, "choiceTop3": 0, "choiceNll": 0., "byAction": {}}
    for start in range(0, len(samples), batch_size):
        batch = samples[start:start + batch_size]
        planes, globals_, actions, mask, targets = batch_tensors(batch, device)
        logits = model(planes, globals_, actions, mask)
        losses = nn.functional.cross_entropy(logits, targets, reduction="none").cpu().tolist()
        order = logits.argsort(dim=1, descending=True).cpu().tolist()
        for sample, loss, ranked in zip(batch, losses, order):
            if len(sample["actions"]) == 1:
                totals["forced"] += 1
                continue
            totals["choices"] += 1
            correct = int(ranked[0] == sample["target"])
            totals["choiceTop1"] += correct
            totals["choiceTop3"] += int(sample["target"] in ranked[:3])
            totals["choiceNll"] += loss
            item = totals["byAction"].setdefault(sample["action"], {"count": 0, "correct": 0})
            item["count"] += 1
            item["correct"] += correct
    count = totals["choices"]
    for key in ("choiceTop1", "choiceTop3", "choiceNll"):
        totals[key] = totals[key] / count if count else None
    for item in totals["byAction"].values():
        item["accuracy"] = item["correct"] / item["count"]
    totals["macroActionAccuracy"] = (sum(item["accuracy"] for item in totals["byAction"].values()) /
                                    len(totals["byAction"]) if totals["byAction"] else None)
    return totals


def export_model(model, path, metadata):
    meta = {**metadata, "format": MODEL_FORMAT, "config": model.config,
            "featureVersion": FEATURE_VERSION, "featureSignature": FEATURE_SIGNATURE,
            "actionVersion": ACTION_SCHEMA_VERSION, "ruleset": RULESET}
    arrays = {key: value.detach().cpu().numpy().astype(np.float32)
              for key, value in model.state_dict().items()}
    arrays["metadata"] = np.asarray(json.dumps(meta, ensure_ascii=False, sort_keys=True))
    with Path(path).open("wb") as handle:
        np.savez_compressed(handle, **arrays)


def train(samples, config, *, players, epochs, batch_size, learning_rate, seed,
          device, smoke, output, report):
    if epochs < 1 or batch_size < 1 or not 0 < learning_rate < 1:
        raise ValueError("invalid training parameters")
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    partitions, groups = split_games(samples, seed, smoke)
    model = CandidatePolicy(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    training = [sample for sample in partitions["train"] if len(sample["actions"]) > 1]
    if not training:
        raise ValueError("training set contains no actual choices")
    history, best_loss, best_state = [], float("inf"), None
    initial = evaluate(model, partitions["train"], device, batch_size)
    for epoch in range(epochs):
        model.train()
        total = 0.
        order = rng.permutation(len(training))
        for start in range(0, len(order), batch_size):
            batch = [training[i] for i in order[start:start + batch_size]]
            planes, globals_, actions, mask, targets = batch_tensors(batch, device)
            optimizer.zero_grad(set_to_none=True)
            loss = nn.functional.cross_entropy(model(planes, globals_, actions, mask), targets)
            if not torch.isfinite(loss):
                raise ValueError("non-finite training loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
            total += loss.item() * len(batch)
        validation = evaluate(model, partitions["validation"], device, batch_size)
        row = {"epoch": epoch + 1, "trainLoss": total / len(training), "validation": validation}
        history.append(row)
        criterion = validation["choiceNll"] if validation else row["trainLoss"]
        if criterion is None:
            raise ValueError("validation partition contains no actual choices")
        if criterion < best_loss:
            best_loss = criterion
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        print(json.dumps({"epoch": epoch + 1, "trainLoss": row["trainLoss"], "validationNll":
                          validation["choiceNll"] if validation else None}), flush=True)
    model.load_state_dict(best_state)
    purpose = "smoke" if smoke else "behavior-cloning"
    report.update({"purpose": purpose, "playerCount": players, "seed": seed, "config": config,
                   "device": str(device), "epochs": epochs, "batchSize": batch_size,
                   "learningRate": learning_rate, "weightDecay": 1e-4,
                   "parameterCount": sum(p.numel() for p in model.parameters()), "gameSplit": groups,
                   "initialTrain": initial, "history": history,
                   "metrics": {name: evaluate(model, values, device, batch_size) for name, values in partitions.items()},
                   "versions": {"torch": torch.__version__, "numpy": np.__version__},
                   "limitations": ["Behavior cloning predicts recorded choices, not optimal actions.",
                                   "No playing-strength or counterfactual value claim."]})
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    export_model(model, output, {"playerCount": players, "purpose": purpose,
                                "training": report})
    return model, report
