#!/usr/bin/env python3
"""Audit available evidence or evaluate offline, separately labelled risk layers.

No coefficients are installed in advisor.py. Complete-replay labels must be
produced and reviewed externally; a file hash proves identity, not authenticity.
"""
import argparse
import ast
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
LAYERS = ("tenpai", "ronGivenTenpai", "paymentGivenRon", "dealIn")
PUBLIC_FIELDS = ("selfSeat", "playerCount", "hand", "handComplete", "historyComplete",
                 "rivers", "melds", "north", "doras", "riichi", "riichiPending",
                 "riichiStep", "doubleRiichi", "round", "lastStep", "left")


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root=ROOT):
    source = root / "src/advisor.py"
    model = next(ast.literal_eval(node.value) for node in ast.parse(source.read_text()).body
                 if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "MODEL" for t in node.targets))
    recording = root / "tests/fixtures/recording"
    frames = json.loads((recording / "capture.json").read_text())
    events = json.loads((recording / "decoded-events.json").read_text())
    draws = [event for event in events if event["action"] == "ActionDealTile"]
    fixtures = []
    for path in sorted((root / "tests/fixtures").glob("advisor*cases.json")):
        fixtures.append({"path": str(path.relative_to(root)), "sha256": sha256(path),
                         "cases": len(json.loads(path.read_text())["cases"])})
    return {"schemaVersion": 1, "status": "not-calibrated-no-labelled-dataset",
            "model": model, "advisorSha256": sha256(source),
            "recording": {"frames": len(frames), "events": len(events),
                          "firstStep": min(e["step"] for e in events),
                          "lastStep": max(e["step"] for e in events),
                          "openingEvents": sum(e["action"] == "ActionNewRound" for e in events),
                          "terminalEvents": sum(e["action"] in ("ActionHule", "ActionNoTile", "ActionLiuJu")
                                                for e in events),
                          "draws": len(draws), "hiddenDraws": sum(e["tile"] is None for e in draws),
                          "sha256": sha256(recording / "decoded-events.json")},
            "fixtures": fixtures,
            "missing": ["complete matches with reliable start/end timestamps",
                        "opponent tenpai at each decision, including non-winning hands",
                        "legal ron on every candidate at that decision, including furiten and yaku",
                        "discarder payment given ron, including honba and excluding existing deposits",
                        "reviewed exporter and labeler with reproducible source replay hashes"],
            "conclusion": "Regression fixtures and truncated observations do not calibrate probabilities."}


def public_state(raw, step):
    """Construct the ONLY object passed to the predictor; labels never enter it."""
    require(all(key in raw for key in PUBLIC_FIELDS if key != "doubleRiichi"),
            "Missing public risk input; do not silently invent an empty river or bonus")
    require(raw.get("handComplete") is True and raw.get("historyComplete") is True,
            "Complete own hand and public history are required")
    require(raw.get("canDiscard") is True, "Snapshot must be taken before an own discard")
    require(raw.get("lastStep") == step, "Decision step differs from public snapshot")
    result = {key: raw[key] for key in PUBLIC_FIELDS if key in raw}
    result["round"] = {key: raw.get("round", {}).get(key, 0) for key in ("chang", "ju", "ben")}
    result["rivers"] = []
    for river in raw["rivers"]:
        projected = []
        for discard in river:
            require(type(discard.get("step")) is int and 0 <= discard["step"] <= step,
                    "River contains missing/future event step")
            require(type(discard.get("moqie")) is bool, "River requires observed moqie flags")
            require(type(discard.get("called", False)) is bool, "Called flag must be boolean")
            projected.append({key: discard[key] for key in ("tile", "called", "step", "moqie")
                              if key in discard})
        require(all(a["step"] < b["step"] for a, b in zip(projected, projected[1:])),
                "River must retain chronological event order")
        result["rivers"].append(projected)
    result["melds"] = []
    for melds in raw["melds"]:
        projected = []
        for meld in melds:
            require(type(meld.get("step")) is int and 0 <= meld["step"] <= step,
                    "Meld requires its formation/update step at or before the decision")
            projected.append({key: meld[key] for key in ("type", "tiles", "froms", "step") if key in meld})
        result["melds"].append(projected)
    require(all(value is None or type(value) is int and 0 <= value <= step
                for value in result.get("riichiStep", [])), "Future riichi step")
    return result


def extract(document, directory, predictor=None):
    """Join full-decision labels to public-only predictions, never terminal proxies."""
    if predictor is None:
        sys.path.insert(0, str(ROOT / "src"))
        import advisor as predictor
    require(document.get("schemaVersion") == 1, "Unsupported dataset schema")
    source = document["source"]
    require(source["kind"] in ("complete-replay", "synthetic-test"), "Unsupported source kind")
    require(source["labelMethod"] == "omniscient-state-before-discard", "Terminal-only labels are invalid")
    require(all(isinstance(source.get(k), str) and source[k] for k in ("exporter", "labeler", "ruleset")),
            "Exporter, labeler and ruleset are required")
    require(source["ruleset"] == "majsoul-standard", "This predictor requires its supported ruleset")
    rows, matches, identities, replay_hashes = [], {}, set(), set()
    for match in document["matches"]:
        match_id = match["id"]
        require(match_id not in matches, "Duplicate match ID")
        start, end = timestamp(match["startedAt"]), timestamp(match["endedAt"])
        require(start < end, "Invalid match interval")
        path = (directory / match["replay"]["path"]).resolve()
        digest = sha256(path)
        require(digest == match["replay"]["sha256"], "Replay hash mismatch")
        require(digest not in replay_hashes, "Same replay appears under multiple match IDs")
        replay_hashes.add(digest)
        matches[match_id] = {"startedAt": match["startedAt"], "endedAt": match["endedAt"], "sha256": digest}
        for decision in match["decisions"]:
            step = decision["step"]
            require(type(step) is int and step >= 0, "Invalid decision step")
            state = public_state(decision["publicState"], step)
            players, own = state["playerCount"], state["selfSeat"]
            require(players in (3, 4) and type(own) is int and 0 <= own < players, "Invalid seats")
            require(all(len(state[key]) >= players and all(type(value) is bool for value in state[key])
                        for key in ("riichi", "riichiPending")), "Invalid public riichi flags")
            require(start <= timestamp(decision["at"]) <= end, "Decision outside match time")
            identity = (match_id, decision["roundId"], step, own)
            require(identity not in identities, "Duplicate decision identity")
            identities.add(identity)
            require(state["hand"] and len(state["rivers"]) >= players and len(state["melds"]) >= players,
                    "Incomplete decision snapshot")
            require(len(state["hand"]) == 14 - 3 * len(state["melds"][own]), "Invalid own discard hand size")
            remaining = predictor.unseen_counts(state)
            enemies = predictor._opponents(state, remaining)
            targets = sorted(set(state["hand"]))
            labels = decision["opponents"]
            require(len(labels) == players - 1 and {label["seat"] for label in labels} == set(range(players)) - {own},
                    "Each opponent needs a label exactly once")
            predicted = {tile: {item["seat"]: item for item in predictor._danger(tile, remaining, enemies)[2]}
                         for tile in targets}
            for label in labels:
                enemy = label["seat"]
                ready = label["tenpai"]
                require(type(ready) is bool, "Tenpai must be an omniscient boolean label")
                require(set(label["tiles"]) == set(targets), "Label every distinct held tile, including red identity")
                river = state["rivers"][enemy]
                features = {"playerCount": players, "riichi": bool(state.get("riichi", [False] * 4)[enemy]),
                            "meldCount": len(state["melds"][enemy]), "riverLength": len(river),
                            "tedashiCount": sum(not d["moqie"] for d in river),
                            "river": river, "left": state.get("left")}
                common = {"matchId": match_id, "roundId": decision["roundId"], "step": step,
                          "selfSeat": own, "opponentSeat": enemy, "features": features}
                first = predicted[targets[0]][enemy]
                rows.append({**common, "layer": "tenpai", "prediction": first["tenpaiProbability"],
                             "outcome": int(ready)})
                for tile in targets:
                    truth = label["tiles"][tile]
                    hit, paid = truth["legalRon"], truth["lossPoints"]
                    require(type(hit) is bool and (not hit or ready), "Ron requires tenpai")
                    require(type(paid) in (int, float) and math.isfinite(paid) and
                            (paid > 0 if hit else paid == 0), "Invalid conditional payment label")
                    estimate = predicted[tile][enemy]
                    require(all(type(estimate[key]) in (int, float) and math.isfinite(estimate[key]) and 0 <= estimate[key] <= 1
                                for key in ("tenpaiProbability", "conditionalRonProbability")), "Invalid prediction")
                    require(math.isfinite(estimate["lossPoints"]) and estimate["lossPoints"] > 0, "Invalid predicted payment")
                    item = {**common, "tile": tile}
                    rows.append({**item, "layer": "dealIn", "prediction": estimate["tenpaiProbability"] *
                                 estimate["conditionalRonProbability"], "outcome": int(hit)})
                    if ready:
                        rows.append({**item, "layer": "ronGivenTenpai",
                                     "prediction": estimate["conditionalRonProbability"], "outcome": int(hit)})
                    if hit:
                        rows.append({**item, "layer": "paymentGivenRon",
                                     "prediction": estimate["lossPoints"], "outcome": paid})
    return {"schemaVersion": 1, "source": source, "model": predictor.MODEL,
            "advisorSha256": sha256(ROOT / "src/advisor.py"), "matches": matches, "rows": rows,
            "labelVerification": "Source file hashes verified; semantic correctness requires external exporter/labeler audit."}


def probability_metrics(rows, bins):
    if not rows:
        return {"count": 0}
    groups = [[] for _ in range(bins)]
    for row in rows:
        groups[min(bins - 1, int(row["prediction"] * bins))].append(row)
    reliability = [{"bin": i, "count": len(group),
                    "predicted": sum(r["prediction"] for r in group) / len(group),
                    "observed": sum(r["outcome"] for r in group) / len(group)}
                   for i, group in enumerate(groups) if group]
    return {"count": len(rows), "positives": sum(r["outcome"] for r in rows),
            "brier": sum((r["prediction"] - r["outcome"]) ** 2 for r in rows) / len(rows),
            "logLoss": -sum(r["outcome"] * math.log(max(1e-12, r["prediction"])) +
                            (1 - r["outcome"]) * math.log(max(1e-12, 1 - r["prediction"])) for r in rows) / len(rows),
            "ece": sum(g["count"] * abs(g["predicted"] - g["observed"]) for g in reliability) / len(rows),
            "deterministicContradictions": sum(r["prediction"] in (0, 1) and r["prediction"] != r["outcome"] for r in rows),
            "reliability": reliability}


def metrics(rows, layer, bins):
    if layer != "paymentGivenRon":
        return probability_metrics(rows, bins)
    if not rows:
        return {"count": 0}
    errors = [r["prediction"] - r["outcome"] for r in rows]
    return {"count": len(rows), "mae": sum(abs(e) for e in errors) / len(rows),
            "rmse": math.sqrt(sum(e * e for e in errors) / len(rows)),
            "bias": sum(errors) / len(rows)}


def fit(rows, bins):
    """Offline candidates only; leave structural zero/one probabilities fixed."""
    fitted = {}
    for layer in ("tenpai", "ronGivenTenpai"):
        groups = [[] for _ in range(bins)]
        for row in rows:
            if row["layer"] == layer and 0 < row["prediction"] < 1:
                groups[min(bins - 1, int(row["prediction"] * bins))].append(row["outcome"])
        fitted[layer] = [{"count": len(group), "rate": sum(group) / len(group) if group else None} for group in groups]
    payments = [r for r in rows if r["layer"] == "paymentGivenRon"]
    denominator = sum(r["prediction"] for r in payments)
    fitted["paymentGivenRon"] = {"count": len(payments),
                                "scale": sum(r["outcome"] for r in payments) / denominator if denominator else 1.}
    return fitted


def adjusted(row, fitted, bins):
    p, layer = row["prediction"], row["layer"]
    if layer == "paymentGivenRon":
        return {**row, "prediction": p * fitted[layer]["scale"]}
    if p in (0, 1):
        return row
    rate = fitted[layer][min(bins - 1, int(p * bins))]["rate"]
    return {**row, "prediction": p if rate is None else rate}


def evaluate(extracted, train_end, validation_end, bins=10):
    first, second = timestamp(train_end), timestamp(validation_end)
    require(first < second and bins > 0, "Ordered cutoffs and positive bin count required")
    split, excluded = {}, []
    for key, match in extracted["matches"].items():
        start, end = timestamp(match["startedAt"]), timestamp(match["endedAt"])
        if end < first:
            split[key] = "train"
        elif start >= first and end < second:
            split[key] = "validation"
        elif start >= second:
            split[key] = "test"
        else:
            excluded.append(key)
    train = [r for r in extracted["rows"] if split.get(r["matchId"]) == "train"]
    fitted = fit(train, bins)
    result = {}
    for partition in ("train", "validation", "test"):
        rows = [r for r in extracted["rows"] if split.get(r["matchId"]) == partition]
        layers = {}
        for layer in LAYERS:
            selected = [r for r in rows if r["layer"] == layer]
            layers[layer] = {"baseline": metrics(selected, layer, bins)}
            # The joint check uses the ORIGINAL product. Never independently
            # calibrate it into a number inconsistent with the two components.
            if layer != "dealIn":
                layers[layer]["trainFittedCandidate"] = metrics([adjusted(r, fitted, bins) for r in selected], layer, bins)
        result[partition] = {"matches": sum(part == partition for part in split.values()), "layers": layers}
    complete = all(result[part]["matches"] for part in result)
    return {"schemaVersion": 1, "status": "synthetic-pipeline-check" if extracted["source"]["kind"] == "synthetic-test"
            else "offline-candidate-evaluation" if complete else "insufficient-split-coverage",
            "model": extracted["model"], "advisorSha256": extracted["advisorSha256"],
            "source": extracted["source"], "labelVerification": extracted["labelVerification"],
            "split": {"trainEnd": train_end, "validationEnd": validation_end, "matches": split,
                      "excludedBoundaryMatches": excluded}, "bins": bins,
            "fittedOnTrainOnly": fitted, "evaluation": result,
            "limitations": ["No advisor coefficients were changed; this does not establish stronger play.",
                            "Equal-width frequency bins and a payment scale are diagnostic candidates, not validated deployed models.",
                            "Rows in a match and alternative tiles are correlated; row counts are not independent sample counts.",
                            "Ron means legal eligibility, not an opponent's voluntary acceptance or multi-ron settlement.",
                            "Dataset coverage and semantic labels require independent audit; source hashes alone cannot prove them."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "extract", "evaluate"))
    parser.add_argument("--dataset", type=Path, help="Reviewed complete-replay export, schema described in docs/advisor-calibration.md")
    parser.add_argument("--train-end", help="Exclusive training match end cutoff; ISO timestamp with timezone")
    parser.add_argument("--validation-end", help="Exclusive validation match end cutoff; test starts here")
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            report = audit()
        else:
            require(args.dataset is not None, "--dataset is required")
            extracted = extract(json.loads(args.dataset.read_text()), args.dataset.resolve().parent)
            extracted["datasetSha256"] = sha256(args.dataset)
            if args.command == "extract":
                report = extracted
            else:
                require(args.train_end is not None and args.validation_end is not None, "Both time cutoffs are required")
                report = evaluate(extracted, args.train_end, args.validation_end, args.bins)
                report["datasetSha256"] = extracted["datasetSha256"]
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Calibration input rejected: {exc}\n")
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
