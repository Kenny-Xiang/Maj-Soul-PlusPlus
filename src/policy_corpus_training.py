"""Game-streamed behavior cloning from a hash-bound sample manifest."""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

import numpy as np
import torch
from torch import nn

from policy_model import PolicyModel
from policy_features import ACTIONS
from policy_encoded_cache import cache_binding, cache_path, read_cache, write_cache, encoder_signature
from policy_split import read_split
from policy_training import (CandidatePolicy, batch_tensors, evaluate, export_model,
                             read_samples, split_games)


def read_manifest(path, seed, max_games=None, split_file=None, partitions=None):
    path = Path(path).resolve()
    if partitions is not None and split_file is None:
        raise ValueError("partition selection requires a frozen split")
    if max_games is not None and max_games < 3:
        raise ValueError("max_games must allow at least three distinct games")
    if split_file is not None and max_games is not None:
        raise ValueError("max_games cannot change a frozen split")
    rows, seen_games, seen_paths, seen_hashes, source_hashes = [], set(), set(), set(), {}
    converter_signatures = {}
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
            source_hashes[identifier] = row.get("sourceSha256")
            if split_file is not None:
                signature = row.get("converterSignature")
                if not isinstance(signature, str) or not re.fullmatch("[0-9a-f]{64}", signature):
                    raise ValueError("frozen training requires a converter signature")
                converter_signatures[identifier] = signature
            rows.append({"gameId": identifier, "path": sample_path, "sha256": digest, "samples": count,
                         "matchMetadata": row.get("matchMetadata")})
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"{path.name}:{number}: {error}") from error
    rows.sort(key=lambda row: hashlib.sha256(f"{seed}:{row['gameId']}".encode()).digest())
    selected = rows if max_games is None else rows[:max_games]
    split_audit = None
    if split_file is None:
        _, groups = split_games([{"game": row["gameId"]} for row in selected], seed)
    else:
        groups, split_audit = read_split(split_file, source_hashes, partitions)
        selected_ids = {game for group in groups.values() for game in group}
        selected = [row for row in selected if row["gameId"] in selected_ids]
        signatures = {converter_signatures[game] for game in selected_ids}
        if len(signatures) != 1:
            raise ValueError("frozen training mixes converter signatures")
    by_id = {row["gameId"]: row for row in selected}
    partitions = {name: [by_id[identifier] for identifier in group] for name, group in groups.items()}
    audit = {"manifest": path.name, "manifestSha256": hashlib.sha256(payload).hexdigest(),
             "manifestGames": len(rows), "manifestSamples": sum(row["samples"] for row in rows),
             "maxGames": max_games, "selectedGames": len(selected),
             "selectedPartitions": list(groups),
             "selectedSamples": sum(row["samples"] for row in selected),
             "selectedGameCounts": {name: len(group) for name, group in groups.items()},
             "matchLengthCoverage": dict(Counter(
                 {1: "east", 2: "south"}.get((row["matchMetadata"] or {}).get("roundCount"), "unknown")
                 for row in selected))}
    if split_audit is not None:
        audit["frozenSplit"] = split_audit
        audit["converterSignature"] = next(iter(signatures))
    return partitions, groups, audit


def load_game(row, players, encoded_cache=None):
    binding = cache_binding(row, players) if encoded_cache is not None else None
    cached = cache_path(encoded_cache, binding) if binding is not None else None
    if cached is not None and cached.exists():
        if hashlib.sha256(row["path"].read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Sample file SHA256 mismatch: {row['path'].name}")
        return read_cache(cached, binding)
    samples, audit = read_samples([row["path"]], players)
    if audit["inputs"][0]["sha256"] != row["sha256"]:
        raise ValueError(f"Sample file SHA256 mismatch: {row['path'].name}")
    if len(samples) != row["samples"] or any(sample["game"] != row["gameId"] for sample in samples):
        raise ValueError(f"Sample count or game identity differs from manifest: {row['path'].name}")
    if cached is not None:
        write_cache(cached, binding, samples, audit)
    return samples, audit


def prepare_game_cache(args):
    row, players, encoded_cache = args
    samples, _ = load_game(row, players, encoded_cache)
    return len(samples)


def save_training_checkpoint(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".training-", delete=False) as handle:
        staged = Path(handle.name)
    try:
        with staged.open("wb") as handle:
            torch.save(payload, handle)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def merge_metrics(items):
    """Merge per-game scores by decisions, preserving action numerators."""
    from policy_training import OPPORTUNITY_COUNTS, OPPORTUNITY_SCOPE, finalize_opportunities
    totals = {"samples": 0, "choices": 0, "forced": 0,
              "choiceTop1": 0, "choiceTop3": 0, "choiceNll": 0., "byAction": {},
              "byOpportunity": {}, "opportunityScope": OPPORTUNITY_SCOPE}
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
        for action, values in item["byOpportunity"].items():
            dest = totals["byOpportunity"].setdefault(action, dict.fromkeys(OPPORTUNITY_COUNTS, 0))
            for name in OPPORTUNITY_COUNTS:
                dest[name] += values[name]
    count = totals["choices"]
    for name in ("choiceTop1", "choiceTop3", "choiceNll"):
        totals[name] = totals[name] / count if count else None
    for values in totals["byAction"].values():
        values["accuracy"] = values["correct"] / values["count"]
    totals["macroActionAccuracy"] = (sum(v["accuracy"] for v in totals["byAction"].values()) /
                                    len(totals["byAction"]) if totals["byAction"] else None)
    finalize_opportunities(totals["byOpportunity"])
    return totals


def evaluate_corpus(model, rows, players, device, batch_size, phase="evaluation", encoded_cache=None,
                    game_window=16):
    if type(game_window) is not int or game_window < 1:
        raise ValueError("evaluation game_window must be a positive integer")
    actions, labels = Counter(), Counter()
    duplicate_count = 0

    def scores():
        nonlocal duplicate_count
        group, group_games = [], 0
        for completed_games, row in enumerate(rows, 1):
            samples, audit = load_game(row, players, encoded_cache)
            actions.update(audit["actions"])
            labels.update(audit["labelSources"])
            duplicate_count += audit["duplicateSamples"]
            group.extend(samples)
            group_games += 1
            del samples
            if (group_games == game_window or completed_games % 100 == 0 or
                    completed_games == len(rows)):
                result = evaluate(model, group, device, batch_size)
                group, group_games = [], 0
                if completed_games % 100 == 0:
                    print(json.dumps({"phase": phase, "completedGames": completed_games,
                                      "totalGames": len(rows)}), flush=True)
                yield result

    metrics = merge_metrics(scores())
    return metrics, {"games": len(rows), "samples": metrics["samples"],
                     "actions": dict(actions), "labelSources": dict(labels),
                     "duplicateSamples": duplicate_count}


def verify_export(model, path, rows, players, device, encoded_cache=None):
    deployed = PolicyModel(path)
    model.eval()
    error, matching, checked = 0., True, 0
    for row in rows:
        samples, _ = load_game(row, players, encoded_cache)
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


def _validate_action_boundary_weights(weights):
    if weights is not None and (not isinstance(weights, dict) or any(
            key not in ("riichi", "daiminkan") or isinstance(value, bool) or
            not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
            for key, value in weights.items())):
        raise ValueError("action boundary weights must map riichi/daiminkan to finite nonnegative numbers")


def supervised_loss(logits, targets, actions, action_weights, opportunity_weights=None,
                    action_boundary_weights=None):
    """Weight recorded full-candidate labels; keep every legal negative example."""
    _validate_action_boundary_weights(action_boundary_weights)
    losses = nn.functional.cross_entropy(logits, targets, reduction="none")
    types = actions[:, :, :len(ACTIONS)]
    weights = torch.ones_like(losses)
    if opportunity_weights:
        opportunity = losses.new_tensor([opportunity_weights.get(action, 1.) for action in ACTIONS])
        weights = (types * opportunity).amax(dim=(1, 2)).clamp_min(1.)
    if action_weights:
        labels = losses.new_tensor([action_weights.get(action, 1.) for action in ACTIONS])
        recorded = types[torch.arange(len(targets), device=targets.device), targets]
        weights = weights * (recorded * labels).sum(dim=1)
    for action, coefficient in (action_boundary_weights or {}).items():
        if coefficient == 0:
            continue
        focal = types[:, :, ACTIONS.index(action)] > 0
        offered = focal.any(dim=1)
        valid = types[offered].any(dim=2)
        scores = logits[offered].masked_fill(~valid, -torch.inf)
        focal = focal[offered]
        positive = focal.gather(1, targets[offered, None]).squeeze(1)
        actual_group = torch.where(positive[:, None], focal, ~focal) & valid
        # The complement contains every true negative type; full CE still
        # distinguishes its exact recorded candidate. Keep the base denominator.
        boundary = torch.logsumexp(scores, dim=1) - torch.logsumexp(
            scores.masked_fill(~actual_group, -torch.inf), dim=1)
        extra = torch.zeros_like(losses)
        extra[offered] = boundary
        losses = losses + coefficient * extra
    return (losses * weights).sum() / weights.sum()


def select_train_monitor(rows, seed, count):
    if count is None:
        return []
    if type(count) is not int or count < 1:
        raise ValueError("train monitor games must be a positive integer")
    return sorted(rows, key=lambda row: hashlib.sha256(
        f"train-monitor-v1:{seed}:{row['gameId']}".encode()).digest())[:count]


def train_corpus(manifest, output, *, players=4, epochs=1, batch_size=64,
                 learning_rate=1e-3, seed=42, device="cpu", max_games=None, config=None, split_file=None,
                 encoded_cache=None, resume=False, checkpoint_every_games=1000, game_window=1,
                 final_lr_ratio=1., action_weights=None, opportunity_weights=None,
                 action_boundary_weights=None, validation_only=False,
                 train_game_limit=None, validation_game_limit=None, save_epoch_models=False,
                 train_monitor_games=None):
    if (players not in (3, 4) or epochs < 1 or batch_size < 1 or not 0 < learning_rate < 1 or
            checkpoint_every_games < 1 or game_window < 1):
        raise ValueError("invalid training parameters")
    action_weights = dict(action_weights or {})
    opportunity_weights = dict(opportunity_weights or {})
    _validate_action_boundary_weights(action_boundary_weights)
    action_boundary_weights = dict(action_boundary_weights or {})
    if (not 0 < final_lr_ratio <= 1 or
            any(key not in ACTIONS or not math.isfinite(value) or value <= 0
                for key, value in list(action_weights.items()) + list(opportunity_weights.items()))):
        raise ValueError("invalid learning rate ratio or action loss weights")
    if ((train_game_limit is not None or validation_game_limit is not None) and not validation_only):
        raise ValueError("partition limits are only permitted in validation-only experiments")
    if any(value is not None and value < 1 for value in (train_game_limit, validation_game_limit)):
        raise ValueError("partition limits must be positive")
    select_train_monitor([], seed, train_monitor_games)
    started = time.monotonic()
    partitions, groups, data_audit = read_manifest(manifest, seed, max_games, split_file,
                                                 ("train", "validation") if validation_only and split_file else None)
    if validation_only:
        partitions = {"train": partitions["train"][:train_game_limit],
                      "validation": partitions["validation"][:validation_game_limit]}
        groups = {name: [row["gameId"] for row in rows] for name, rows in partitions.items()}
        data_audit = {**data_audit, "validationOnly": True,
                      "selectedGames": sum(len(rows) for rows in partitions.values()),
                      "selectedSamples": sum(row["samples"] for rows in partitions.values() for row in rows),
                      "selectedGameCounts": {name: len(rows) for name, rows in partitions.items()}}
    monitor_rows = select_train_monitor(partitions["train"], seed, train_monitor_games)
    monitor_ids = [row["gameId"] for row in monitor_rows]
    monitor_audit = None if train_monitor_games is None else {
        "requestedGames": train_monitor_games, "games": len(monitor_rows), "gameIds": monitor_ids,
        "identitySha256": hashlib.sha256(json.dumps(monitor_ids, separators=(",", ":")).encode()).hexdigest(),
        "selection": "sha256(train-monitor-v1:{seed}:{gameId}) ascending over actual training games",
        "scope": "Fixed training games evaluated without loss weights; not independent held-out data."}
    config = config or {"channels": 64, "blocks": 3, "hidden": 256}
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = CandidatePolicy(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    history, best_loss, best_state, best_epoch = [], float("inf"), None, None
    maximum_game_samples, maximum_window_samples, steps = 0, 0, 0
    checkpoint_path = Path(output).with_suffix(".resume.pt")
    binding = {"version": 1, "dataAudit": data_audit, "gameSplit": groups, "players": players,
               "epochs": epochs, "batchSize": batch_size, "learningRate": learning_rate,
               "seed": seed, "config": config, "gameWindow": game_window,
               "finalLrRatio": final_lr_ratio, "actionWeights": action_weights,
               "opportunityWeights": opportunity_weights,
               "actionBoundaryWeights": action_boundary_weights,
               "trainMonitor": monitor_audit,
               "validationOnly": validation_only, "saveEpochModels": save_epoch_models,
               "encoderSignature": encoder_signature(),
               "trainerSignature": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    start_epoch, cursor, order, loss_sum, choices, prior_elapsed = 0, 0, None, 0., 0, 0.
    if resume:
        saved = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        if saved["binding"] != binding:
            raise ValueError("resume checkpoint differs in source, split, encoder or training parameters")
        if saved.get("completed"):
            raise ValueError("training checkpoint already completed; final test was evaluated")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        rng.bit_generator.state = saved["numpyRng"]
        torch.set_rng_state(saved["torchRng"])
        start_epoch, cursor, order = saved["epoch"], saved["cursor"], saved["order"]
        loss_sum, choices = saved["lossSum"], saved["choices"]
        history, best_loss, best_state, best_epoch = (saved[name] for name in
                                                    ("history", "bestLoss", "bestState", "bestEpoch"))
        maximum_game_samples, steps = saved["maximumGameSamples"], saved["steps"]
        maximum_window_samples = saved["maximumWindowSamples"]
        prior_elapsed = saved["elapsedSeconds"]

    def persist(epoch, cursor, order, loss_sum, choices, completed=False):
        save_training_checkpoint(checkpoint_path, {
            "binding": binding, "model": model.state_dict(), "optimizer": optimizer.state_dict(),
            "numpyRng": rng.bit_generator.state, "torchRng": torch.get_rng_state(),
            "epoch": epoch, "cursor": cursor, "order": order, "lossSum": loss_sum, "choices": choices,
            "history": history, "bestLoss": best_loss, "bestState": best_state, "bestEpoch": best_epoch,
            "maximumGameSamples": maximum_game_samples, "steps": steps,
            "maximumWindowSamples": maximum_window_samples,
            "elapsedSeconds": prior_elapsed + time.monotonic() - started, "completed": completed})

    for epoch in range(start_epoch, epochs):
        model.train()
        epoch_lr = learning_rate * (final_lr_ratio + (1 - final_lr_ratio) *
                                    (1 + math.cos(math.pi * epoch / max(1, epochs - 1))) / 2)
        for group in optimizer.param_groups:
            group["lr"] = epoch_lr
        if order is None:
            order = rng.permutation(len(partitions["train"])).tolist()
            cursor, loss_sum, choices = 0, 0., 0
        for window_start in range(cursor, len(order), game_window):
            completed_games = min(window_start + game_window, len(order))
            training, window_samples = [], 0
            for game_index in order[window_start:completed_games]:
                samples, _ = load_game(partitions["train"][game_index], players, encoded_cache)
                maximum_game_samples = max(maximum_game_samples, len(samples))
                window_samples += len(samples)
                training.extend(sample for sample in samples if len(sample["actions"]) > 1)
                del samples
            maximum_window_samples = max(maximum_window_samples, window_samples)
            decision_order = rng.permutation(len(training))
            for start in range(0, len(decision_order), batch_size):
                batch = [training[index] for index in decision_order[start:start + batch_size]]
                planes, globals_, actions, mask, targets = batch_tensors(batch, device)
                optimizer.zero_grad(set_to_none=True)
                loss = supervised_loss(model(planes, globals_, actions, mask), targets, actions,
                                       action_weights, opportunity_weights, action_boundary_weights)
                if not torch.isfinite(loss):
                    raise ValueError("non-finite training loss")
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.)
                optimizer.step()
                loss_sum += loss.item() * len(batch)
                choices += len(batch)
                steps += 1
            del training
            if completed_games // checkpoint_every_games > window_start // checkpoint_every_games:
                persist(epoch, completed_games, order, loss_sum, choices)
            if completed_games // 100 > window_start // 100:
                print(json.dumps({"phase": "training", "epoch": epoch + 1,
                                  "completedGames": completed_games, "trainGames": len(partitions["train"]),
                                  "choices": choices, "optimizerSteps": steps,
                                  "loss": loss_sum / choices if choices else None,
                                  "elapsedSeconds": round(prior_elapsed + time.monotonic() - started, 1)}), flush=True)
        if not choices:
            raise ValueError("training partition contains no actual choices")
        validation, _ = evaluate_corpus(model, partitions["validation"], players, device, batch_size,
                                        phase=f"epoch-{epoch + 1}-validation", encoded_cache=encoded_cache)
        criterion = validation["choiceNll"]
        if criterion is None:
            raise ValueError("validation partition contains no actual choices")
        row = {"epoch": epoch + 1, "learningRate": epoch_lr, "trainLoss": loss_sum / choices,
               "trainChoices": choices, "validation": validation}
        if monitor_rows:
            row["trainMonitor"], _ = evaluate_corpus(
                model, monitor_rows, players, device, batch_size,
                phase=f"epoch-{epoch + 1}-train-monitor", encoded_cache=encoded_cache)
        history.append(row)
        if save_epoch_models:
            epoch_path = Path(output).with_suffix(f".epoch-{epoch + 1}.npz")
            epoch_path.parent.mkdir(parents=True, exist_ok=True)
            export_model(model, epoch_path, {"playerCount": players, "purpose": "behavior-cloning",
                         "training": {"phase": "validation-complete", "epoch": epoch + 1,
                                      "validation": validation, "dataAudit": data_audit, "gameSplit": groups}})
        if criterion < best_loss:
            best_loss, best_epoch = criterion, epoch + 1
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            checkpoint = Path(output).with_suffix(".checkpoint.npz")
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            export_model(model, checkpoint, {"playerCount": players, "purpose": "behavior-cloning",
                         "training": {"phase": "validation-complete", "epoch": epoch + 1,
                                      "validation": validation, "dataAudit": data_audit, "gameSplit": groups}})
        print(json.dumps({"epoch": epoch + 1, "trainGames": len(partitions["train"]),
                          "trainChoices": choices, "trainLoss": row["trainLoss"],
                          "validationNll": criterion}), flush=True)
        order, cursor = None, 0
        persist(epoch + 1, 0, None, 0., 0)
    model.load_state_dict(best_state)
    metrics, partition_audits = {}, {}
    for name, rows in partitions.items():
        if validation_only and name == "train":
            continue
        metrics[name], partition_audits[name] = evaluate_corpus(model, rows, players, device, batch_size,
                                                              phase=f"final-{name}", encoded_cache=encoded_cache)
    report = {"purpose": "behavior-cloning", "playerCount": players, "seed": seed,
              "config": config, "device": str(device), "epochs": epochs,
              "batchSize": batch_size, "learningRate": learning_rate, "weightDecay": 1e-4,
              "finalLrRatio": final_lr_ratio, "actionWeights": action_weights,
              "opportunityWeights": opportunity_weights,
              "actionBoundaryWeights": action_boundary_weights,
              "trainMonitor": monitor_audit,
              "validationOnly": validation_only,
              "parameterCount": sum(p.numel() for p in model.parameters()),
              "gameSplit": groups, "dataAudit": {**data_audit, "partitions": partition_audits},
              "history": history, "bestEpoch": best_epoch, "metrics": metrics,
              "streaming": {"unit": "bounded-game-window", "gameWindow": game_window,
                            "largestTrainingGameSamples": maximum_game_samples,
                            "largestTrainingWindowSamples": maximum_window_samples,
                            "optimizerSteps": steps, "gameAndDecisionOrder": "shuffled-each-epoch",
                            "encodedCache": encoded_cache is not None, "resumed": resume,
                            "checkpointEveryGames": checkpoint_every_games},
              "versions": {"torch": torch.__version__, "numpy": np.__version__},
              "limitations": ["Behavior cloning predicts recorded choices, not optimal actions.",
                              "Only selected manifest games were trained; no playing-strength claim.",
                              "Match length and round index are excluded from model inputs by design."]}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".policy-corpus-", suffix=".npz", delete=False) as handle:
        staged = Path(handle.name)
    try:
        export_model(model, staged, {"playerCount": players, "purpose": "behavior-cloning", "training": report})
        parity, digest = verify_export(model, staged, partitions["train"], players, device, encoded_cache)
        report.update(exportParity=parity, modelSha256=digest,
                      elapsedSeconds=prior_elapsed + time.monotonic() - started)
        report_path = output.with_suffix(".report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        os.replace(staged, output)
        persist(epochs, 0, None, 0., 0, completed=True)
    finally:
        staged.unlink(missing_ok=True)
    return model, report
