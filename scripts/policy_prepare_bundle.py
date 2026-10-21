#!/usr/bin/env python3
"""Prepare two completed full-corpus policies for the macOS application bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policy_bundle import BUNDLE_FORMAT, MODEL_NAMES


def full_model(path, players, minimum_games):
    from policy_model import PolicyModel

    path = Path(path).resolve()
    model = PolicyModel(path)
    report_path = path.with_suffix(".report.json")
    report_payload = report_path.read_bytes()
    report = json.loads(report_payload)
    training = model.metadata.get("training", {})
    if (model.metadata["playerCount"] != players or model.metadata["purpose"] != "behavior-cloning" or
            report.get("playerCount") != players or report.get("purpose") != "behavior-cloning" or
            report.get("modelSha256") != model.sha256):
        raise ValueError(f"{players}-player model/report identity does not match")
    if (not training or not training.get("metrics") or
            any(report.get(key) != value for key, value in training.items())):
        raise ValueError("model must contain the matching completed training report")
    audit = report["dataAudit"]
    games = audit.get("selectedGames")
    split = audit.get("frozenSplit")
    if (type(games) is not int or games < minimum_games or games != audit.get("manifestGames") or
            audit.get("maxGames") is not None or not isinstance(split, dict) or
            split.get("unit") != "whole-game-all-seats" or not split.get("sha256")):
        raise ValueError("full-corpus bundle requires all manifest games and a frozen whole-game split")
    groups = report.get("gameSplit", {})
    if (set(groups) != {"train", "validation", "test"} or
            {key: len(value) for key, value in groups.items()} != audit.get("selectedGameCounts") or
            any(not value for value in groups.values())):
        raise ValueError("training report game partitions are inconsistent")
    ids = [game for group in groups.values() for game in group]
    if len(ids) != games or len(set(ids)) != games:
        raise ValueError("training report game partitions overlap or omit games")
    parity = report.get("exportParity", {})
    if parity.get("argmaxAgreement") is not True or not parity.get("samples") or parity.get("maxAbsError", 1) > 1e-4:
        raise ValueError("model export parity has not passed")
    entry = {"file": MODEL_NAMES[players], "playerCount": players, "sha256": model.sha256,
             "report": MODEL_NAMES[players].replace(".npz", ".report.json"),
             "reportSha256": hashlib.sha256(report_payload).hexdigest(),
             "selectedGames": games, "selectedGameCounts": audit["selectedGameCounts"],
             "manifestSha256": audit["manifestSha256"], "frozenSplitSha256": split["sha256"],
             "featureSignature": model.metadata["featureSignature"],
             "actionVersion": model.metadata["actionVersion"]}
    return path, report_path, entry


def prepare_bundle(models, output, minimum_games=40000):
    if set(models) != {3, 4} or type(minimum_games) is not int or minimum_games < 40000:
        raise ValueError("full bundle requires both player slots and at least 40000 games per corpus")
    validated = {players: full_model(path, players, minimum_games) for players, path in models.items()}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"format": BUNDLE_FORMAT, "minimumGames": minimum_games,
                "models": {str(players): item[2] for players, item in validated.items()}}
    for path, report, entry in validated.values():
        shutil.copyfile(path, output / entry["file"])
        shutil.copyfile(report, output / entry["report"])
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def validate_bundle(folder):
    """Recheck the exact staged files immediately before PyInstaller collects them."""
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    minimum = manifest.get("minimumGames")
    if (manifest.get("format") != BUNDLE_FORMAT or set(manifest.get("models", {})) != {"3", "4"} or
            type(minimum) is not int or minimum < 40000):
        raise ValueError("invalid full policy bundle manifest")
    for players, name in MODEL_NAMES.items():
        _, _, expected = full_model(folder / name, players, minimum)
        if manifest["models"][str(players)] != expected:
            raise ValueError(f"staged {players}-player policy differs from its manifest")
    return [(str(folder / name), "policy-models") for name in
            ("manifest.json", *(item[key] for item in manifest["models"].values() for key in ("file", "report")))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--three-player", type=Path, required=True)
    parser.add_argument("--four-player", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "build/policy-models")
    parser.add_argument("--minimum-games", type=int, default=40000)
    args = parser.parse_args()
    try:
        manifest = prepare_bundle({3: args.three_player, 4: args.four_player}, args.output, args.minimum_games)
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({"bundle": str(args.output.resolve()), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
