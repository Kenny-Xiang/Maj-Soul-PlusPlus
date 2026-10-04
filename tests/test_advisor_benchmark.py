"""Offline fixture validity and reproducible version-comparison checks."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from advisor import advise, unseen_counts


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/advisor_compare.py"
spec = importlib.util.spec_from_file_location("advisor_compare", SCRIPT)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


class AdvisorBenchmarkTests(unittest.TestCase):
    def test_representative_snapshots_are_valid_and_do_not_mutate(self):
        cases = comparison.load_cases(comparison.FIXTURES)
        tags = {tag for case in cases for tag in case["tags"]}
        self.assertTrue({"efficiency", "no-yaku", "furiten", "riichi", "opponent-riichi",
                         "chi", "pon", "ankan", "daiminkan", "shouminkan", "kita", "three-player",
                         "late-wall", "one-shanten", "red-five", "waiting-analysis"} <= tags)
        for case in cases:
            with self.subTest(case=case["id"]):
                snapshot = deepcopy(case["state"])
                self.assertGreaterEqual(min(unseen_counts(snapshot)), 0)
                advice = advise(snapshot)
                self.assertEqual(advice["status"], case["expectedStatus"], advice)
                self.assertEqual(snapshot, case["state"])
                candidates = advice["candidates"]
                self.assertTrue(candidates)
                self.assertEqual(len({c["actionId"] for c in candidates}), len(candidates))
                for candidate in candidates:
                    for field in ("winProbability", "dealInProbability"):
                        self.assertGreaterEqual(candidate[field], 0)
                        self.assertLessEqual(candidate[field], 1)
                # Reject NaN/Infinity anywhere, including nested replacement branches.
                json.dumps(advice, allow_nan=False)

    def test_nearest_rank_latency_and_fixture_selection(self):
        self.assertEqual(comparison.latency([3]),
                         {"count": 1, "medianMs": 3, "p95Ms": 3, "maxMs": 3})
        self.assertEqual(comparison.latency(list(range(20, 0, -1))),
                         {"count": 20, "medianMs": 10.5, "p95Ms": 19, "maxMs": 20})
        selected = comparison.load_cases(comparison.FIXTURES, ["closed-tsumo-only-one-shanten"])
        self.assertEqual([case["id"] for case in selected], ["closed-tsumo-only-one-shanten"])
        with self.assertRaisesRegex(ValueError, "Unknown case"):
            comparison.load_cases(comparison.FIXTURES, ["not-a-fixture"])

    def test_native_accounts_are_distinct_from_derived_residuals(self):
        cases = comparison.load_cases(comparison.FIXTURES, ["closed-tsumo-only-tenpai"])
        report = comparison.run_version(ROOT / "src", cases, warmups=0, repeats=1)
        item = report["cases"][cases[0]["id"]]
        for candidate in item["advice"]["candidates"]:
            self.assertEqual(item["nativeScoreBreakdowns"][candidate["actionId"]], candidate["scoreBreakdown"])
            self.assertNotIn("residual", candidate["scoreBreakdown"])
            self.assertIn("residual", item["scoreComponents"][candidate["actionId"]])

    def test_same_ref_isolated_comparison_preserves_analysis_and_reports_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            # Neither subprocess may accidentally import another checkout's module.
            (directory / "advisor.py").write_text("raise RuntimeError('wrong advisor import')\n")
            output = directory / "report.json"
            subprocess.run(
                [sys.executable, str(SCRIPT), "--baseline", "HEAD", "--current-ref", "HEAD",
                 "--case", "closed-tsumo-only-tenpai", "--case", "closed-tsumo-only-one-shanten",
                 "--warmups", "1", "--repeats", "2", "--output", str(output)],
                env={**os.environ, "PYTHONPATH": str(directory)},
                capture_output=True, text=True, check=True)
            report = json.loads(output.read_text())
        self.assertEqual(report["baseline"]["source"], report["current"]["source"])
        self.assertEqual(report["baseline"]["model"], report["current"]["model"])
        self.assertEqual(report["method"]["warmupPasses"], 1)
        for version in ("baseline", "current"):
            results = report[version]
            self.assertEqual(results["latency"]["count"], 4)
            self.assertEqual(len(results["source"]["sourceSha256"]), 64)
            for case in results["cases"].values():
                self.assertEqual(case["latency"]["count"], 2)
                self.assertTrue(case["consistentAcrossRepeats"])
                self.assertEqual(len(case["scoreComponents"]), len(case["advice"]["candidates"]))
            waiting = results["cases"]["closed-tsumo-only-one-shanten"]["advice"]
            self.assertEqual(waiting["status"], "analysis")
            self.assertEqual(waiting["best"]["action"], "wait")
        for change in report["changes"].values():
            self.assertFalse(change["statusChanged"])
            self.assertFalse(change["recommendationChanged"])
            self.assertEqual(change["candidateChanges"], [])


if __name__ == "__main__":
    unittest.main()
