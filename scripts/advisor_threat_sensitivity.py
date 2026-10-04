#!/usr/bin/env python3
"""Offline ranking sensitivity to the two public-evidence priors, not fitting."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

from advisor_compare import FIXTURES, ROOT, load_cases, recommendation

sys.path.insert(0, str(ROOT / "src"))
import advisor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cases = load_cases(FIXTURES) + load_cases(ROOT / "tests/fixtures/advisor_threat_cases.json")
    runs = []
    for yaku in (.4, .6, .8):
        for flush in (.15, .25, .35):
            results = {}
            with patch.object(advisor, "OPEN_YAKU_CONFIDENCE", yaku), patch.object(
                    advisor, "FLUSH_ROUTE_WEIGHT", flush):
                for case in cases:
                    state = deepcopy(case["state"])
                    advice = advisor.advise(state)
                    if advice["status"] != case["expectedStatus"] or state != case["state"]:
                        raise RuntimeError(f"Invalid evaluation: {case['id']}: {advice['status']}")
                    results[case["id"]] = {"recommendation": recommendation(advice),
                                            "candidates": [{k: c[k] for k in (
                                                "actionId", "score", "scoreBreakdown", "opponentRisks")}
                                                           for c in advice["candidates"]]}
            runs.append({"openYakuConfidence": yaku, "flushRouteWeight": flush, "cases": results})
    default = next(r for r in runs if r["openYakuConfidence"] == .6 and r["flushRouteWeight"] == .25)
    for run in runs:
        run["changedRecommendations"] = [key for key, result in run["cases"].items()
                                          if result["recommendation"] != default["cases"][key]["recommendation"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"model": advisor.MODEL, "cases": cases, "runs": runs},
                                     ensure_ascii=False, allow_nan=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
