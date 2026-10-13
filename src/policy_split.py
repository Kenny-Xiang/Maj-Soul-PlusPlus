"""Frozen, source-bound whole-game partitions for corpus experiments."""
import hashlib
import json
from pathlib import Path
import re


PARTITIONS = ("train", "validation", "test")


def freeze_split(corpus, preferred_ids, excluded, *, count=10000, seed=42, previous=None):
    if count < 3:
        raise ValueError("at least three games are required")
    by_id = {row["gameId"]: row for row in corpus}
    if len(by_id) != len(corpus):
        raise ValueError("duplicate source game")
    for field in ("compressedSha256", "eventsSha256"):
        if len({row[field] for row in corpus}) != len(corpus):
            raise ValueError(f"duplicate source {field}")
    preferred, reserved = set(preferred_ids), set(excluded)
    if not preferred <= by_id.keys() or not reserved <= by_id.keys():
        raise ValueError("selection contains unknown games")
    order = lambda game: hashlib.sha256(f"frozen-v1:{seed}:{game}".encode()).digest()
    retained = {name: [] for name in PARTITIONS}
    if previous is not None:
        prior = json.loads(Path(previous).read_text())
        prior_ids = set(prior["sources"])
        if not prior_ids <= by_id.keys():
            raise ValueError("previous split has games outside the corpus")
        retained, previous_audit = read_split(previous, {
            game: by_id[game]["compressedSha256"] for game in prior_ids})
        if any(prior["sources"][game]["eventsSha256"] != by_id[game]["eventsSha256"]
               for game in prior_ids):
            raise ValueError("previous split event hash differs")
        if prior_ids & reserved or not set(prior.get("excluded", {})) <= reserved:
            raise ValueError("previous split exclusions must be preserved")
        if count < len(prior_ids):
            raise ValueError("cannot shrink a previous split")
    else:
        prior_ids = set()
    selected = sorted(prior_ids, key=order)
    selected += sorted(preferred - reserved - prior_ids, key=order)[:count - len(selected)]
    selected += sorted(by_id.keys() - reserved - set(selected), key=order)[:count - len(selected)]
    if len(selected) != count:
        raise ValueError("not enough unreserved games")
    selected.sort(key=order)
    held = max(1, count // 10)
    targets = {"train": count - 2 * held, "validation": held, "test": held}
    groups = {name: list(retained[name]) for name in PARTITIONS}
    additions = iter(game for game in selected if game not in prior_ids)
    for name in ("validation", "test", "train"):
        if len(groups[name]) > targets[name]:
            raise ValueError("previous partition exceeds the new target")
        groups[name].extend(next(additions) for _ in range(targets[name] - len(groups[name])))
    result = {"schemaVersion": 1, "seed": seed, "unit": "whole-game-all-seats",
            "groups": groups, "excluded": excluded,
            "sources": {game: {field: by_id[game][field] for field in ("compressedSha256", "eventsSha256")}
                        for game in sorted(selected)},
            "selection": {"games": count, "retainedPreferred": len(set(selected) & preferred),
                          "replacementGames": len(set(selected) - preferred)}}
    if previous is not None:
        result["previousSplit"] = {**previous_audit, "preservedGames": len(prior_ids)}
    return result


def read_split(path, source_hashes):
    payload = Path(path).read_bytes()
    data = json.loads(payload)
    if data.get("schemaVersion") != 1 or data.get("unit") != "whole-game-all-seats":
        raise ValueError("unsupported frozen split")
    groups = data["groups"]
    if set(groups) != set(PARTITIONS) or any(not isinstance(groups[name], list) or not groups[name]
                                           for name in PARTITIONS):
        raise ValueError("all three split partitions must be nonempty")
    games = [game for name in PARTITIONS for game in groups[name]]
    if len(games) != len(set(games)):
        raise ValueError("game overlaps frozen partitions")
    if set(games) != set(source_hashes) or set(data["sources"]) != set(games):
        raise ValueError("frozen split and manifest games differ")
    if set(games) & set(data.get("excluded", {})):
        raise ValueError("calibration game leaked into frozen partitions")
    for field in ("compressedSha256", "eventsSha256"):
        values = [data["sources"][game][field] for game in games]
        if any(not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value) for value in values):
            raise ValueError("invalid frozen source hash")
        if len(values) != len(set(values)):
            raise ValueError("duplicate frozen source hash")
    for game in games:
        if data["sources"][game]["compressedSha256"] != source_hashes[game]:
            raise ValueError(f"frozen split source hash differs: {game}")
    return groups, {"file": Path(path).name, "sha256": hashlib.sha256(payload).hexdigest(),
                    "schemaVersion": 1, "unit": data["unit"], "excludedGames": len(data.get("excluded", {}))}
