#!/usr/bin/env python3
"""Reproduce inference timing and complete-output checks without changing the repo."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]

FIXTURES = (
    "advisor_cases.json", "advisor_threat_cases.json", "advisor_phase_cases.json",
    "advisor_performance_logged_cases.json", "advisor_policy_logged_cases.json",
    "advisor_route_cases.json", "advisor_timeout_cases.json", "advisor_rank_cases.json",
    "advisor_latency_cases.json",
)
TIMEOUT_IDS = ("live-timeout-serial-578", "live-timeout-serial-1017")
LATENCY_IDS = ("live-latency-serial-1600", "live-latency-serial-1643", "live-latency-serial-1661")
COLD_IDS = ("pon-red-choices", "one-shanten-followup-risk", "shouminkan-red", *TIMEOUT_IDS, *LATENCY_IDS)
ABS_TOLERANCE = 1e-8
REL_TOLERANCE = 1e-12


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def timed_out(advice):
    return advice["status"] == "unavailable" and "时间预算" in advice.get("message", "")


def without_elapsed(advice):
    return {key: value for key, value in advice.items() if key != "elapsedMs"}


def compare_values(before, after):
    result = {"maxAbsError": 0., "maxAbsErrorPath": None, "numericChanged": 0,
              "numericMismatch": 0, "stringMismatch": 0, "otherMismatch": 0,
              "mismatches": []}

    def mismatch(kind, path, old, new):
        result[kind] += 1
        result["mismatches"].append({"kind": kind, "path": path, "before": old, "after": new})

    def visit(old, new, path):
        if type(old) in (int, float) and type(new) in (int, float):
            error = abs(new - old)
            result["numericChanged"] += int(error != 0)
            if error > result["maxAbsError"]:
                result["maxAbsError"], result["maxAbsErrorPath"] = error, path
            if not math.isclose(old, new, abs_tol=ABS_TOLERANCE, rel_tol=REL_TOLERANCE):
                mismatch("numericMismatch", path, old, new)
        elif isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                if key not in old or key not in new:
                    mismatch("otherMismatch", f"{path}.{key}", old.get(key), new.get(key))
                else:
                    visit(old[key], new[key], f"{path}.{key}")
        elif isinstance(old, list) and isinstance(new, list):
            if len(old) != len(new):
                mismatch("otherMismatch", f"{path}.length", len(old), len(new))
            for index, (left, right) in enumerate(zip(old, new)):
                visit(left, right, f"{path}[{index}]")
        elif type(old) is not type(new) or old != new:
            mismatch("stringMismatch" if isinstance(old, str) and isinstance(new, str)
                     else "otherMismatch", path, old, new)

    visit(before, after, "$")
    return result


def diagnostic_worker(source):
    """Only the legacy timeout reference uses an extended in-memory deadline."""
    request = json.load(sys.stdin)
    sys.path.insert(0, request.pop("scripts"))
    from advisor_compare import evaluate
    sys.path.insert(0, str(source))
    import advisor
    require_budget(source)
    advisor.SEARCH_SECONDS = 120.
    result = evaluate(source, **request)
    result["diagnosticOnlyBudgetSeconds"] = 120
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


def advice_worker_process(source):
    """Exercise the default background worker and its real cancellation callback."""
    case = json.load(sys.stdin)
    sys.path.insert(0, str(source))
    import advice_worker
    require_budget(source)
    if Path(advice_worker.__file__).resolve() != (source / "advice_worker.py").resolve():
        raise ValueError("AdviceWorker import does not match the frozen source")
    worker = advice_worker.AdviceWorker()
    import advisor
    if Path(advisor.__file__).resolve() != (source / "advisor.py").resolve():
        worker.close()
        raise ValueError("Advisor import does not match the frozen source")
    try:
        started = time.perf_counter()
        worker.submit(f"benchmark:{case['id']}", case["state"])
        with worker.condition:
            received = worker.condition.wait_for(lambda: worker.completed is not None, timeout=10)
            packet = worker.take_result() if received else None
        elapsed = (time.perf_counter() - started) * 1000
    finally:
        worker.close()
        worker.thread.join(3)
    advice = packet["advice"] if packet else None
    result = {"caseId": case["id"], "submitToResultMs": elapsed,
              "advisorElapsedMs": advice.get("elapsedMs") if advice else None,
              "expectedStatus": case["expectedStatus"], "status": advice.get("status") if advice else None,
              "received": received, "workerStopped": not worker.thread.is_alive(),
              "statusPass": received and advice["status"] == case["expectedStatus"],
              "timeout": bool(advice and timed_out(advice)),
              "over1000Ms": elapsed > 1000,
              "rankedCandidateCount": advice.get("rankedCandidateCount") if advice else None,
              "envelope": {key: value for key, value in packet.items() if key != "advice"} if packet else None,
              "packet": packet}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


def require_budget(source):
    tree = ast.parse((source / "advisor.py").read_text())
    budgets = [ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "SEARCH_SECONDS"
                       for target in node.targets)]
    if budgets != [2.0]:
        raise ValueError(f"Expected unchanged 2-second search budget: {source}, {budgets}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT, help="Checkout to compare (default: this repository)")
    parser.add_argument("--baseline", required=True, help="Git reference for the source before optimization")
    parser.add_argument("--baseline-results", type=Path, help="Reuse baseline measurements from a completed artifact directory")
    parser.add_argument("--legacy-timeout-reference", action="store_true",
                        help="Allow 120-second baseline diagnostic references for the two legacy timeout cases only")
    parser.add_argument("--live", type=Path, help="Optional local public-state fixture export")
    parser.add_argument("--artifacts", type=Path, help="New output directory (default: build/advisor-inference/<timestamp>)")
    args = parser.parse_args()
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo / "scripts"))
    from advisor_compare import latency, load_cases, run_version, snapshot_source, source_hash

    output = args.artifacts or repo / "build/advisor-inference" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    runner_files = [Path(__file__).resolve(), repo / "scripts/advisor_compare.py"]
    (output / "scripts").mkdir()
    runner_info = {}
    for path in runner_files:
        contents = path.read_bytes()
        (output / "scripts" / path.name).write_bytes(contents)
        runner_info[path.name] = hashlib.sha256(contents).hexdigest()
    fixture_paths = [repo / "tests/fixtures" / name for name in FIXTURES]
    public = [case for path in fixture_paths for case in load_cases(path)]
    live = load_cases(args.live) if args.live else []
    cases = public + live
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Combined fixtures contain duplicate IDs")
    by_id = {case["id"]: case for case in cases}
    if not set(COLD_IDS) <= by_id.keys():
        raise ValueError("Missing required cold-start cases")
    live_ids = {case["id"] for case in live}
    rank_ids = {case["id"] for case in load_cases(repo / "tests/fixtures/advisor_rank_cases.json")}
    groups = {"all": set(ids), "rank": rank_ids, "latency": set(LATENCY_IDS)}
    if live_ids:
        groups["live"] = live_ids
    timeout_ids = set(TIMEOUT_IDS)
    ordinary_cases = [case for case in cases if case["id"] not in timeout_ids]
    timeout_cases = [by_id[case_id] for case_id in TIMEOUT_IDS]
    save(output / "fixtures.json", {"schemaVersion": 1, "cases": cases})
    sources, source_info = {}, {}
    for version, ref in (("baseline", args.baseline), ("current", None)):
        destination = output / version
        destination.mkdir()
        sources[version], source_info[version] = snapshot_source(repo, destination, ref)
        require_budget(sources[version])
    fixture_info = [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "caseCount": len(load_cases(path))} for path in [*fixture_paths, *([args.live] if args.live else [])]]
    fixture_info.append({"path": str((output / "fixtures.json").resolve()),
                         "sha256": hashlib.sha256((output / "fixtures.json").read_bytes()).hexdigest(),
                         "caseCount": len(cases)})
    reuse = args.baseline_results.resolve() if args.baseline_results else None
    previous, reused_files = {}, []
    if reuse:
        previous = json.loads((reuse / "summary.json").read_text())
        if previous.get("runnerSha256") != runner_info:
            raise ValueError("Reused baseline runner metadata is missing or does not match")
        expected = {"budgetSeconds": 2, "rankedLimitBothVersions": 3, "warmupPasses": 1, "measuredPasses": 3,
                    "legacyTimeoutReference": args.legacy_timeout_reference}
        environment = {"python": sys.version, "platform": platform.platform(),
                       "mahjong": importlib.metadata.version("mahjong")}
        if (previous["sources"]["baseline"]["sourceSha256"] != source_info["baseline"]["sourceSha256"] or
                not previous["fixtures"][-1]["sha256"] == hashlib.sha256((reuse / "fixtures.json").read_bytes()).hexdigest() == fixture_info[-1]["sha256"] or
                previous["environment"] != environment or
                any(previous["method"].get(key) != value for key, value in expected.items())):
            raise ValueError("Reused baseline source, fixtures, environment, or settings do not match")

    def run(label, version, selected, warmups, repeats, internal=False, ranked_limit=3,
            extended_reference=False):
        if reuse and version == "baseline":
            original = reuse / f"{label}-baseline.json"
            raw = original.read_bytes()
            result = json.loads(raw)
            shutil.copyfile(original, output / original.name)
            reused_files.append({"label": label, "source": str(original), "sha256": hashlib.sha256(raw).hexdigest()})
            print(f"Reusing {label}: baseline from {reuse}", flush=True)
            return result
        print(f"Running {label}: {version}, {len(selected)} cases", flush=True)
        if extended_reference:
            if version != "baseline" or not internal or warmups or repeats != 1:
                raise ValueError("Extended budget is only permitted for one legacy diagnostic reference")
            if {case["id"] for case in selected} != timeout_ids:
                raise ValueError("Extended budget is only permitted for the two recorded timeout cases")
            request = {"scripts": str(repo / "scripts"), "cases": selected, "warmups": 0, "repeats": 1,
                       "include_internal": True, "ranked_limit": ranked_limit}
            completed = subprocess.run(
                [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--diagnostic-worker",
                 str(sources[version])], input=json.dumps(request), capture_output=True, text=True, check=True)
            result = json.loads(completed.stdout)
        else:
            result = run_version(sources[version], selected, warmups, repeats,
                                 include_internal=internal, ranked_limit=ranked_limit)
        save(output / f"{label}-{version}.json", result)
        return result

    # Every case starts its own current-version interpreter and empty caches.
    current_cold_all = {case["id"]: run(f"cold-all-{index + 1}-{case['id']}", "current", [case], 0, 1)
                        for index, case in enumerate(cases)}
    cold, cold_order = {version: {} for version in sources}, []
    for case_index, case_id in enumerate(COLD_IDS):
        for repeat in range(3):
            versions = ("baseline", "current") if (case_index * 3 + repeat) % 2 == 0 else ("current", "baseline")
            for version in versions:
                cold_order.append({"case": case_id, "repeat": repeat + 1, "version": version,
                                   "reused": bool(reuse and version == "baseline")})
                result = run(f"cold-{case_id}-{repeat + 1}", version, [by_id[case_id]], 0, 1)
                cold[version].setdefault(case_id, []).append(result)
    warm = {version: run("warm", version, cases, 1, 3) for version in ("baseline", "current")}

    worker_results = {}
    for case_id in (*COLD_IDS, *(case["id"] for case in public if case["id"] in rank_ids)):
        print(f"Running actual AdviceWorker: current, {case_id}", flush=True)
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--advice-worker",
             str(sources["current"])], input=json.dumps(by_id[case_id]),
            capture_output=True, text=True, check=True)
        result = json.loads(completed.stdout)
        save(output / f"actual-worker-{case_id}-current.json", result)
        worker_results[case_id] = {key: value for key, value in result.items() if key != "packet"}

    # Independent fresh workers collect complete public outputs and unrounded
    # private candidate fields. Their measured durations are not benchmark data.
    diagnostics = {}
    for label, selected, ranked_limit, extended in (
            ("equivalence-prefix", ordinary_cases, 3, False),
            ("equivalence-full", ordinary_cases, None, False),
            ("equivalence-timeout-reference-prefix", timeout_cases, 3, args.legacy_timeout_reference),
            ("equivalence-timeout-reference-full", timeout_cases, None, args.legacy_timeout_reference)):
        results = {version: run(label, version, selected, 0, 1, True, ranked_limit,
                                extended_reference=extended and version == "baseline")
                   for version in ("baseline", "current")}
        comparisons, incomplete = {}, []
        candidate_count = 0
        for case in selected:
            case_id = case["id"]
            before, after = (results[version]["cases"][case_id] for version in ("baseline", "current"))
            if timed_out(before["advice"]) or timed_out(after["advice"]):
                incomplete.append({"id": case_id, "baselineTimeout": timed_out(before["advice"]),
                                   "currentTimeout": timed_out(after["advice"])})
                continue
            # Preserve list order, actions, explanations, and all nonnumeric
            # values exactly. Compare every numerical field without rounding.
            comparisons[case_id] = {
                "public": compare_values(without_elapsed(before["advice"]), without_elapsed(after["advice"])),
                "private": compare_values(before["internalCandidates"], after["internalCandidates"])}
            candidate_count += len(after["advice"].get("candidates", []))
            for result in (before, after):
                public_ids = {candidate["actionId"] for candidate in result["advice"].get("candidates", [])}
                if public_ids != result["internalCandidates"].keys():
                    raise ValueError(f"Incomplete private-candidate capture for {label}: {case_id}")
        fields = {}
        for field in ("public", "private"):
            values = [value[field] for value in comparisons.values()]
            totals = {key: sum(value[key] for value in values)
                      for key in ("numericChanged", "numericMismatch", "stringMismatch", "otherMismatch")}
            fields[field] = {**totals, "maxAbsError": max((value["maxAbsError"] for value in values), default=0.),
                             "equalWithinTolerance": not incomplete and not any(
                                 totals[key] for key in ("numericMismatch", "stringMismatch", "otherMismatch")),
                             "exactValueEquality": not incomplete and not any(totals.values()),
                             "mismatchIds": [case_id for case_id, value in comparisons.items()
                                             if value[field]["mismatches"]]}
        save(output / f"{label}-comparison-details.json", comparisons)
        diagnostics[label] = {"caseCount": len(selected), "completeCaseCount": len(selected) - len(incomplete),
                              "candidateCount": candidate_count, "incomplete": incomplete,
                              "baselineDiagnosticBudgetSeconds": 120 if extended else 2,
                              "currentDiagnosticBudgetSeconds": 2, **fields,
                              "timeouts": {version: results[version]["timeoutCount"] for version in results}}

    def aggregate(result, selected_ids):
        chosen = [item for case_id, item in result["cases"].items() if case_id in selected_ids]
        return {**latency([sample for item in chosen for sample in item["samplesMs"]]),
                "caseCount": len(chosen), "timeoutCount": sum(item["timeoutCount"] for item in chosen),
                "over1000MsCount": sum(sample > 1000 for item in chosen for sample in item["samplesMs"]),
                "over1000MsCaseIds": [case_id for case_id, item in result["cases"].items()
                                      if case_id in selected_ids and any(sample > 1000 for sample in item["samplesMs"])],
                "warmupTimeoutCount": sum(count for case_id, count in result["warmupTimeouts"].items()
                                           if case_id in selected_ids),
                "inconsistentCaseIds": [case_id for case_id, item in result["cases"].items()
                                        if case_id in selected_ids and not item["consistentAcrossRepeats"]]}

    cold_all_combined = {"cases": {case_id: result["cases"][case_id]
                                  for case_id, result in current_cold_all.items()}, "warmupTimeouts": {}}
    for version, source in sources.items():
        if source_hash(source) != source_info[version]["sourceSha256"]:
            raise ValueError(f"Source snapshot changed during the benchmark: {version}")
    for path in runner_files:
        if hashlib.sha256(path.read_bytes()).hexdigest() != runner_info[path.name]:
            raise ValueError(f"Benchmark runner changed during execution: {path}")
    summary = {
        "artifacts": str(output.resolve()), "sources": source_info, "fixtures": fixture_info,
        "baselineReuse": {"source": str(reuse), "summarySha256": hashlib.sha256((reuse / "summary.json").read_bytes()).hexdigest(),
                          "environment": previous["environment"], "files": reused_files} if reuse else None,
        "runnerSha256": runner_info,
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "mahjong": importlib.metadata.version("mahjong")},
        "method": {"budgetSeconds": 2, "rankedLimitBothVersions": 3, "warmupPasses": 1,
                   "legacyTimeoutReference": args.legacy_timeout_reference,
                   "baselineExecution": "all baseline measurements reused from a previous run" if reuse else "measured in this run",
                   "baselineRunSource": previous.get("method", {}).get("baselineRunSource", str(reuse)) if reuse else str(output.resolve()),
                   "measuredPasses": 3, "coldRepeatsPerCase": 3, "coldOrder": cold_order,
                   "currentColdAllPasses": 1,
                   "actualWorker": "Every designated cold-start case and rank-policy fixture runs once in a fresh current-source process using default AdviceWorker; includes its actual cancellation callback and default ranked prefix 3; submit-to-result includes deepcopy and thread dispatch, excludes imports and UI timer/rendering; worker envelope fields are preserved separately from advisor output",
                   "timing": "perf_counter around advise only; imports and process startup excluded",
                   "processes": ("Current cold samples, warm suite, and diagnostic suites run in separate fresh interpreters; every baseline result is reused from the recorded prior run; versions are not interleaved in this run" if reuse else
                                 "fresh interpreter for every cold sample, each warm version, and each diagnostic version"),
                   "equivalence": "independent diagnostic runs; ignore only elapsedMs; compare all numerical fields at full precision with stated tolerances; actions/order/explanations/all nonnumeric values exact",
                   "numericTolerance": {"absolute": ABS_TOLERANCE, "relative": REL_TOLERANCE,
                                        "rule": "math.isclose: abs(delta) <= max(absolute, relative * max(abs(values)))"},
                   "legacyTimeoutReferences": "Disabled; baseline and current diagnostics both retain the 2-second budget" if not args.legacy_timeout_reference else
                                              ("The two 120-second baseline diagnostic references are reused from the previous run; current and all performance measurements use 2 seconds; reference durations excluded from performance" if reuse else
                                               "Only the two timeout cases use baseline in-memory SEARCH_SECONDS=120 for diagnostic output extraction; current and every performance run remain 2 seconds; reference durations excluded from performance"),
                   "p95": "nearest rank", "caseCounts": {"public": len(public), "rank": len(rank_ids), "live": len(live), "all": len(cases)}},
        "currentColdAll": {group: aggregate(cold_all_combined, selected_ids)
                           for group, selected_ids in groups.items()},
        "actualWorkerCurrent": {"cases": worker_results,
                                "latency": latency([result["submitToResultMs"] for result in worker_results.values()]),
                                "timeoutCount": sum(result["timeout"] for result in worker_results.values()),
                                "over1000MsCount": sum(result["over1000Ms"] for result in worker_results.values()),
                                "allStatusPass": all(result["statusPass"] for result in worker_results.values())},
        "warm": {version: {group: aggregate(result, selected_ids) for group, selected_ids in groups.items()}
                 for version, result in warm.items()},
        "cold": {version: {case_id: {**latency([result["cases"][case_id]["samplesMs"][0] for result in results]),
                                    "timeoutCount": sum(result["timeoutCount"] for result in results),
                                    "over1000MsCount": sum(result["cases"][case_id]["samplesMs"][0] > 1000
                                                           for result in results)}
                           for case_id, results in items.items()} for version, items in cold.items()},
        "equivalence": diagnostics,
    }
    save(output / "summary.json", summary)
    print(f"Artifacts: {output.resolve()}", flush=True)
    print("Environment: " + json.dumps(summary["environment"]), flush=True)
    print("Sources: " + json.dumps(source_info, ensure_ascii=False), flush=True)
    print("Fixture SHA256: " + json.dumps({Path(item["path"]).name: item["sha256"]
                                          for item in fixture_info}), flush=True)
    for group, values in summary["currentColdAll"].items():
        print(f"Current cold all {group}: " + json.dumps(values), flush=True)
    for version, groups in summary["warm"].items():
        for group, values in groups.items():
            print(f"Warm {version} {group}: " + json.dumps(values), flush=True)
    for version, values in summary["cold"].items():
        print(f"Cold {version}: " + json.dumps(values), flush=True)
    print("Actual worker current: " + json.dumps(summary["actualWorkerCurrent"], ensure_ascii=False), flush=True)
    for label, values in diagnostics.items():
        print(f"{label}: " + json.dumps(values, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--diagnostic-worker":
        diagnostic_worker(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--advice-worker":
        advice_worker_process(Path(sys.argv[2]))
    else:
        main()
