"""Game-streamed behavior cloning from a hash-bound sample manifest."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

import numpy as np
import torch
from torch import nn

from policy_model import PolicyModel
from policy_training import (CandidatePolicy, batch_tensors, evaluate, export_model,
                             read_samples, split_games)


def read_manifest(path, seed, max_games=None):
    path = Path(path).resolve()
    if max_games is not None and max_games < 3:
        raise ValueError("max_games must allow at least three distinct games")
    rows, seen_games, seen_paths, seen_hashes = [], set(), set(), set()
    payload = path.read_bytes()
    for number, line in enumerate(payload.decode("utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            identifier, relative, digest, count = (row[key] for key in ("gameId", "path", "sha256", "samples"))
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("missing game identity")
            if not isinstance(relative, str) or Path(relative).is_absolute():
                raise ValueError("sample path must be relative to the manifest")
            sample_path = (path.parent / relative).resolve()
            if not sample_path.is_relative_to(path.parent):
                raise ValueError("sample path escapes the corpus")
            if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                raise ValueError("invalid SHA256")
            if type(count) is not int or count < 1:
                raise ValueError("sample count must be positive")
            if identifier in seen_games or sample_path in seen_paths or digest in seen_hashes:
                raise ValueError("duplicate game, sample file or content hash in manifest")
            seen_games.add(identifier)
            seen_paths.add(sample_path)
            seen_hashes.add(digest)
            rows.append({"gameId": identifier, "path": sample_path, "sha256": digest, "samples": count})
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"{path.name}:{number}: {error}") from error
    rows.sort(key=lambda row: hashlib.sha256(f"{seed}:{row['gameId']}".encode()).digest())
    selected = rows if max_games is None else rows[:max_games]
    _, groups = split_games([{"game": row["gameId"]} for row in selected], seed)
    by_id = {row["gameId"]: row for row in selected}
    partitions = {name: [by_id[identifier] for identifier in group] for name, group in groups.items()}
    audit = {"manifest": path.name, "manifestSha256": hashlib.sha256(payload).hexdigest(),
             "manifestGames": len(rows), "manifestSamples": sum(row["samples"] for row in rows),
             "maxGames": max_games, "selectedGames": len(selected),
             "selectedSamples": sum(row["samples"] for row in selected),
             "selectedGameCounts": {name: len(group) for name, group in groups.items()}}
    return partitions, groups, audit


def load_game(row, players):
    samples, audit = read_samples([row["path"]], players)
    if audit["inputs"][0]["sha256"] != row["sha256"]:
        raise ValueError(f"Sample file SHA256 mismatch: {row['path'].name}")
    if len(samples) != row["samples"] or any(sample["game"] != row["gameId"] for sample in samples):
        raise ValueError(f"Sample count or game identity differs from manifest: {row['path'].name}")
    return samples, audit


def merge_metrics(items):
    """Merge per-game scores by decisions, preserving action numerators."""
    totals = {"samples": 0, "choices": 0, "forced": 0,
              "choiceTop1": 0, "choiceTop3": 0, "choiceNll": 0., "byAction": {}}
    for item in items:
        for name in ("samples", "choices", "forced"):
            totals[name] += item[name]
        count = item["choices"]
        if count:
            for name in ("choiceTop1", "choiceTop3"):
                totals[name] += round(item[name] * count)
            totals["choiceNll"] += item["choiceNll"] * count
        for action, values in item["byAction"].items():
            dest = totals["byAction"].setdefault(action, {"count": 0, "correct": 0})
            dest["count"] += values["count"]
            dest["correct"] += values["correct"]
    count = totals["choices"]
    for name in ("choiceTop1", "choiceTop3", "choiceNll"):
        totals[name] = totals[name] / count if count else None
    for values in totals["byAction"].values():
        values["accuracy"] = values["correct"] / values["count"]
    totals["macroActionAccuracy"] = (sum(v["accuracy"] for v in totals["byAction"].values()) /
                                    len(totals["byAction"]) if totals["byAction"] else None)
    return totals


def evaluate_corpus(model, rows, players, device, batch_size):
    actions, labels = Counter(), Counter()
    duplicate_count = 0

    def scores():
        nonlocal duplicate_count
        for row in rows:
            samples, audit = load_game(row, players)
            actions.update(audit["actions"])
            labels.update(audit["labelSources"])
            duplicate_count += audit["duplicateSamples"]
            result = evaluate(model, samples, device, batch_size)
            del samples
            yield result

    metrics = merge_metrics(scores())
    return metrics, {"games": len(rows), "samples": metrics["samples"],
                     "actions": dict(actions), "labelSources": dict(labels),
                     "duplicateSamples": duplicate_count}


def verify_export(model, path, rows, players, device):
    deployed = PolicyModel(path)
    model.eval()
    error, matching, checked = 0., True, 0
    for row in rows:
        samples, _ = load_game(row, players)
        for sample in samples[:32 - checked]:
            planes, globals_, actions, mask, _ = batch_tensors([sample], device)
            with torch.no_grad():
                expected = model(planes, globals_, actions, mask).cpu().numpy()[0]
            actual = deployed.logits(sample["planes"], sample["globals"], sample["actions"])
            error = max(error, float(np.max(np.abs(actual - expected))))
            matching = matching and int(actual.argmax()) == int(expected.argmax())
            checked += 1
        del samples
        if checked == 32:
            break
    if not checked or error > 1e-4 or not matching:
        raise ValueError(f"export parity failed: max error={error}, argmax agreement={matching}")
    return {"samples": checked, "maxAbsError": error, "argmaxAgreement": matching}, deployed.sha256


def train_corpus(manifest, output, *, players=4, epochs=1, batch_size=64,
                 learning_rate=1e-3, seed=42, device="cpu", max_games=None, config=None):
    if players not in (3, 4) or epochs < 1 or batch_size < 1 or not 0 < learning_rate < 1:
        raise ValueError("invalid training parameters")
    started = time.monotonic()
    partitions, groups, data_audit = read_manifest(manifest, seed, max_games)
    config = config or {"channels": 64, "blocks": 3, "hidden": 256}
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = CandidatePolicy(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    history, best_loss, best_state, best_epoch = [], float("inf"), None, None
    maximum_game_samples, steps = 0, 0
    for epoch in range(epochs):
        model.train()
        loss_sum, choices = 0., 0
        for game_index in rng.permutation(len(partitions["train"])):
            samples, _ = load_game(partitions["train"][game_index], players)
            maximum_game_samples = max(maximum_game_samples, len(samples))
            training = [sample for sample in samples if len(sample["actions"]) > 1]
            order = rng.permutation(len(training))
            for start in range(0, len(order), batch_size):
                batch = [training[index] for index in order[start:start + batch_size]]
                planes, globals_, actions, mask, targets = batch_tensors(batch, device)
                optimizer.zero_grad(set_to_none=True)
                loss = nn.functional.cross_entropy(model(planes, globals_, actions, mask), targets)
                if not torch.isfinite(loss):
                    raise ValueError("non-finite training loss")
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.)
                optimizer.step()
                loss_sum += loss.item() * len(batch)
                choices += len(batch)
                steps += 1
            del samples, training
        if not choices:
            raise ValueError("training partition contains no actual choices")
        validation, _ = evaluate_corpus(model, partitions["validation"], players, device, batch_size)
        criterion = validation["choiceNll"]
        if criterion is None:
            raise ValueError("validation partition contains no actual choices")
        row = {"epoch": epoch + 1, "trainLoss": loss_sum / choices,
               "trainChoices": choices, "validation": validation}
        history.append(row)
        if criterion < best_loss:
            best_loss, best_epoch = criterion, epoch + 1
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        print(json.dumps({"epoch": epoch + 1, "trainGames": len(partitions["train"]),
                          "trainChoices": choices, "trainLoss": row["trainLoss"],
                          "validationNll": criterion}), flush=True)
    model.load_state_dict(best_state)
    metrics, partition_audits = {}, {}
    for name, rows in partitions.items():
        metrics[name], partition_audits[name] = evaluate_corpus(model, rows, players, device, batch_size)
    report = {"purpose": "behavior-cloning", "playerCount": players, "seed": seed,
              "config": config, "device": str(device), "epochs": epochs,
              "batchSize": batch_size, "learningRate": learning_rate, "weightDecay": 1e-4,
              "parameterCount": sum(p.numel() for p in model.parameters()),
              "gameSplit": groups, "dataAudit": {**data_audit, "partitions": partition_audits},
              "history": history, "bestEpoch": best_epoch, "metrics": metrics,
              "streaming": {"unit": "one-game", "largestTrainingGameSamples": maximum_game_samples,
                            "optimizerSteps": steps, "gameAndDecisionOrder": "shuffled-each-epoch"},
              "versions": {"torch": torch.__version__, "numpy": np.__version__},
              "limitations": ["Behavior cloning predicts recorded choices, not optimal actions.",
                              "Only selected manifest games were trained; no playing-strength claim."]}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".policy-corpus-", suffix=".npz", delete=False) as handle:
        staged = Path(handle.name)
    try:
        export_model(model, staged, {"playerCount": players, "purpose": "behavior-cloning", "training": report})
        parity, digest = verify_export(model, staged, partitions["train"], players, device)
        report.update(exportParity=parity, modelSha256=digest, elapsedSeconds=time.monotonic() - started)
        report_path = output.with_suffix(".report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        os.replace(staged, output)
    finally:
        staged.unlink(missing_ok=True)
    return model, report
