#!/usr/bin/env python3
"""Compare advisor source versions against identical offline public snapshots."""
import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/advisor_cases.json"


def latency(samples):
    ordered = sorted(samples)
    return {"count": len(samples), "medianMs": statistics.median(ordered),
            "p95Ms": ordered[math.ceil(.95 * len(ordered)) - 1], "maxMs": ordered[-1]}


def load_cases(path, selected=()):
    document = json.loads(Path(path).read_text())
    cases = document["cases"]
    ids = [case["id"] for case in cases]
    if document["schemaVersion"] != 1 or len(set(ids)) != len(ids):
        raise ValueError("Unsupported fixture schema or duplicate case IDs")
    missing = set(selected) - set(ids)
    if missing:
        raise ValueError(f"Unknown case IDs: {sorted(missing)}")
    cases = [case for case in cases if not selected or case["id"] in selected]
    if not cases:
        raise ValueError("At least one fixture is required")
    return cases


def recommendation(advice):
    best = advice.get("best")
    if best is None:
        return {"action": advice.get("action")}
    return {key: best.get(key) for key in
            ("actionId", "action", "tile", "consumed", "calledTile", "followupDiscard")}


def score_components(advice):
    """Expose observable terms; residual is not a separately validated EV term."""
    components = {}
    weight = advice.get("riskWeight", 0)
    for candidate in advice.get("candidates", []):
        income = candidate["winProbability"] * candidate["expectedWinPoints"]
        loss = weight * candidate["expectedDealInLoss"]
        future = weight * candidate.get("futureForcedDealInLoss", 0)
        followup = weight * candidate.get("futureDiscardDealInLoss", 0)
        deposit = candidate.get("expectedRiichiCost", 0)
        dora = candidate.get("newDoraRiskPenalty", 0)
        tsumo = candidate.get("expectedOpponentTsumoLoss", 0)
        liability = candidate.get("expectedOtherRonLiabilityLoss", 0)
        draw = candidate.get("expectedDrawPayment", 0)
        components[candidate["actionId"]] = {
            "winIncome": income, "weightedCurrentDealInLoss": loss,
            "weightedFutureForcedDealInLoss": future, "riichiCost": deposit,
            "weightedFutureDiscardDealInLoss": followup,
            "newDoraRiskPenalty": dora,
            "opponentTsumoLoss": tsumo, "otherRonLiabilityLoss": liability,
            "exhaustiveDrawPayment": draw,
            "residual": candidate["score"] - income + loss + future + followup + deposit + dora + tsumo + liability - draw}
    return components


def diagnostic_fields(value):
    """Preserve unrounded internal accounts as JSON, including Outcome tuples."""
    if hasattr(value, "_asdict"):
        return diagnostic_fields(value._asdict())
    if isinstance(value, dict):
        return {key: diagnostic_fields(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [diagnostic_fields(item) for item in value]
    return value


def evaluate(source, cases, warmups, repeats, include_internal=False, ranked_limit=None):
    # The caller starts a fresh interpreter for each version. No project imports
    # occur before this explicit path is installed, even when PYTHONPATH is set.
    sys.path.insert(0, str(source))
    import advisor
    if Path(advisor.__file__).resolve() != (source / "advisor.py").resolve():
        raise ValueError("Advisor import does not match the isolated source snapshot")
    options = {} if ranked_limit is None else {"ranked_limit": ranked_limit}

    captured = []
    if include_internal:
        explain = advisor._explain_tie

        def capture(candidates):
            explain(candidates)
            # Retain references only inside the timer; copy/encode afterwards.
            captured[:] = [candidates]

        advisor._explain_tie = capture

    warmup_timeouts = {case["id"]: 0 for case in cases}
    for _ in range(warmups):
        for case in cases:
            advice = advisor.advise(deepcopy(case["state"]), **options)
            if advice["status"] == "unavailable" and "时间预算" in advice.get("message", ""):
                warmup_timeouts[case["id"]] += 1
    results = {case["id"]: {"samplesMs": [], "advisorSamplesMs": [],
                            "changedRepeats": []} for case in cases}
    for repeat in range(repeats):
        for case in cases:
            snapshot = deepcopy(case["state"])
            captured.clear()
            started = time.perf_counter()
            advice = advisor.advise(snapshot, **options)
            elapsed = (time.perf_counter() - started) * 1000
            timed_out = advice["status"] == "unavailable" and "时间预算" in advice.get("message", "")
            if advice["status"] != case["expectedStatus"] and not timed_out:
                raise ValueError(f"{case['id']}: expected {case['expectedStatus']}, got {advice}")
            if snapshot != case["state"]:
                raise ValueError(f"{case['id']}: advisor mutated its input snapshot")
            item = results[case["id"]]
            item["samplesMs"].append(elapsed)
            item["advisorSamplesMs"].append(advice.get("elapsedMs"))
            item.setdefault("timeoutCount", 0)
            item["timeoutCount"] += int(timed_out)
            if repeat == 0:
                item["advice"] = advice
                item["scoreComponents"] = score_components(advice)
                item["nativeScoreBreakdowns"] = {c["actionId"]: c["scoreBreakdown"]
                                                  for c in advice.get("candidates", []) if "scoreBreakdown" in c}
                if include_internal:
                    item["internalCandidates"] = {
                        candidate["actionId"]: diagnostic_fields({key: value for key, value in candidate.items()
                                                                   if key.startswith("_")})
                        for candidate in (captured[0] if captured else [])} if not timed_out else {}
            elif ({k: v for k, v in advice.items() if k != "elapsedMs"} !=
                  {k: v for k, v in item["advice"].items() if k != "elapsedMs"}):
                item["changedRepeats"].append({"repeat": repeat + 1, "advice": advice})
    for item in results.values():
        item["latency"] = latency(item["samplesMs"])
        item["consistentAcrossRepeats"] = not item["changedRepeats"]
    return {"model": advisor.MODEL, "cases": results,
            "warmupTimeoutCount": sum(warmup_timeouts.values()),
            "warmupTimeouts": {key: count for key, count in warmup_timeouts.items() if count},
            "timeoutCount": sum(item["timeoutCount"] for item in results.values()),
            "latency": latency([sample for item in results.values() for sample in item["samplesMs"]])}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def source_hash(source):
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(source).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def snapshot_source(repo, destination, ref=None):
    commit = git(repo, "rev-parse", "--verify", f"{ref or 'HEAD'}^{{commit}}").decode().strip()
    if ref:
        archive = git(repo, "archive", "--format=tar", commit, "src")
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(destination, filter="data")
        dirty = []
    else:
        shutil.copytree(repo / "src", destination / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        dirty = git(repo, "status", "--porcelain", "--untracked-files=all", "--", "src").decode().splitlines()
    source = destination / "src"
    return source, {"ref": ref or "working-tree", "commit": commit,
                    "sourceSha256": source_hash(source), "sourceChanges": dirty}


def run_version(source, cases, warmups, repeats, include_internal=False, ranked_limit=None):
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker", str(source)],
        input=json.dumps({"cases": cases, "warmups": warmups, "repeats": repeats,
                          "include_internal": include_internal, "ranked_limit": ranked_limit}),
        text=True, capture_output=True, check=True)
    return json.loads(completed.stdout)


def compare_cases(baseline, current):
    changes = {}
    for case_id, result in current["cases"].items():
        before, after = baseline["cases"][case_id]["advice"], result["advice"]
        old = {c["actionId"]: c for c in before.get("candidates", [])}
        new = {c["actionId"]: c for c in after.get("candidates", [])}
        candidates = []
        for key in sorted(old.keys() | new.keys()):
            if key not in old or key not in new:
                candidates.append({"actionId": key, "change": "added" if key in new else "removed"})
                continue
            fields = sorted(k for k in old[key].keys() | new[key].keys() if old[key].get(k) != new[key].get(k))
            if fields:
                deltas = {k: new[key][k] - old[key][k] for k in fields
                          if type(old[key].get(k)) in (int, float) and type(new[key].get(k)) in (int, float)}
                candidates.append({"actionId": key, "change": "modified",
                                   "changedFields": fields, "numericDeltas": deltas})
        ranked_count = after.get("rankedCandidateCount", len(after.get("candidates", [])))
        changes[case_id] = {"statusChanged": before["status"] != after["status"],
                            "recommendationChanged": recommendation(before) != recommendation(after),
                            "rankedPrefixChanged": before.get("candidates", [])[:ranked_count] !=
                                                   after.get("candidates", [])[:ranked_count],
                            "baselineRecommendation": recommendation(before),
                            "currentRecommendation": recommendation(after), "candidateChanges": candidates}
    return changes


def build_report(repo, fixtures, baseline_ref, current_ref, selected, warmups, repeats, include_internal=False, ranked_limit=None):
    cases = load_cases(fixtures, selected)
    with tempfile.TemporaryDirectory(prefix="advisor-comparison-") as temporary:
        directory = Path(temporary)
        # Snapshot both versions before timing either. The working checkout is
        # never reset, switched, imported directly, or written by this script.
        old_source, old_info = snapshot_source(repo, directory / "baseline", baseline_ref)
        new_source, new_info = snapshot_source(repo, directory / "current", current_ref)
        baseline = {"source": old_info, **run_version(old_source, cases, warmups, repeats,
                                                     include_internal=include_internal)}
        current = {"source": new_info, **run_version(new_source, cases, warmups, repeats,
                                                    include_internal=include_internal, ranked_limit=ranked_limit)}
    return {"schemaVersion": 1,
            "environment": {"python": sys.version, "platform": platform.platform(),
                            "mahjong": importlib.metadata.version("mahjong")},
            "method": {"warmupPasses": warmups, "measuredPasses": repeats,
                       "internalCandidates": include_internal,
                       "currentRankedLimit": ranked_limit, "baselineRankedLimit": None,
                       "caseOrder": [case["id"] for case in cases], "versionOrder": ["baseline", "current"],
                       "timing": "perf_counter around advise only; excludes imports, copying, and process startup",
                       "cache": "fresh process per version; identical ordered full-suite warmup and measurement passes",
                       "p95": "nearest rank: sorted samples[ceil(0.95 * count) - 1]",
                       "scoreComponents": "derived from rounded public fields; residual includes shape, unexposed legacy terms, other adjustments, and rounding",
                       "nativeScoreBreakdowns": "signed original scoring terms and accumulated rounding; v7 exposes mutually exclusive terminal payments separately from heuristic preferences"},
            "fixtures": {"sha256": hashlib.sha256(Path(fixtures).read_bytes()).hexdigest(), "cases": cases},
            "baseline": baseline, "current": current, "changes": compare_cases(baseline, current)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="HEAD", help="Git ref for baseline source (default: HEAD)")
    parser.add_argument("--current-ref", help="Git ref instead of the current working source")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--case", action="append", default=[], help="Case ID to include; repeat for multiple cases")
    parser.add_argument("--warmups", type=int, default=1, help="Excluded full-suite warmup passes (default: 1)")
    parser.add_argument("--repeats", type=int, default=5, help="Measured full-suite passes (default: 5)")
    parser.add_argument("--ranked-limit", type=int,
                        help="Current version's exact ranked prefix; baseline retains full ordering")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path instead of stdout")
    parser.add_argument("--include-internal", action="store_true",
                        help="Include unrounded private candidate accounts for offline diagnosis")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        request = json.load(sys.stdin)
        print(json.dumps(evaluate(args.worker, **request), ensure_ascii=False, allow_nan=False))
        return
    if args.warmups < 0 or args.repeats < 1:
        parser.error("warmups must be nonnegative and repeats must be positive")
    if args.ranked_limit is not None and args.ranked_limit < 2:
        parser.error("ranked-limit must be at least 2")
    try:
        report = build_report(ROOT, args.fixtures.resolve(), args.baseline, args.current_ref,
                              args.case, args.warmups, args.repeats,
                              include_internal=args.include_internal, ranked_limit=args.ranked_limit)
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Comparison failed: {exc}\n{getattr(exc, 'stderr', '') or ''}")
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
        print(json.dumps({"report": str(args.output.resolve()), "baseline": report["baseline"]["latency"],
                          "current": report["current"]["latency"],
                          "timeouts": {version: report[version]["timeoutCount"] for version in ("baseline", "current")},
                          "changedRecommendations": [key for key, value in report["changes"].items()
                                                     if value["recommendationChanged"]]}, indent=2))
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
