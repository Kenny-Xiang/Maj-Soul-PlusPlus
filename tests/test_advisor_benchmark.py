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
from unittest.mock import patch

from advisor import advise, unseen_counts


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/advisor_compare.py"
spec = importlib.util.spec_from_file_location("advisor_compare", SCRIPT)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)
spec = importlib.util.spec_from_file_location("advisor_log_fixtures", ROOT / "scripts/advisor_log_fixtures.py")
log_export = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"advisor_compare": comparison}):
    spec.loader.exec_module(log_export)


class AdvisorBenchmarkTests(unittest.TestCase):
    def test_representative_snapshots_are_valid_and_do_not_mutate(self):
        cases = comparison.load_cases(comparison.FIXTURES)
        cases += comparison.load_cases(ROOT / "tests/fixtures/advisor_threat_cases.json")
        cases += comparison.load_cases(ROOT / "tests/fixtures/advisor_phase_cases.json")
        cases += comparison.load_cases(ROOT / "tests/fixtures/advisor_performance_logged_cases.json")
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
                    for field in ("winProbability", "dealInProbability", "futureDiscardDealInProbability",
                                  "futureForcedDealInProbability"):
                        self.assertGreaterEqual(candidate.get(field, 0), 0)
                        self.assertLessEqual(candidate.get(field, 0), 1)
                    self.assertLessEqual(candidate["winProbability"] + candidate["dealInProbability"] +
                                         candidate.get("futureDiscardDealInProbability", 0) +
                                         candidate.get("futureForcedDealInProbability", 0), 1.0002)
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

    def test_route_snapshots_contain_only_public_engine_inputs(self):
        cases = comparison.load_cases(ROOT / "tests/fixtures/advisor_route_cases.json")
        self.assertEqual(len(cases), 11)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(log_export.public_state(case["state"]), case["state"])
                self.assertGreaterEqual(min(unseen_counts(case["state"])), 0)

    def test_log_export_selects_current_windows_and_removes_private_metadata(self):
        snapshot = deepcopy(comparison.load_cases(comparison.FIXTURES)[0]["state"])
        snapshot.update(canAct=True, canDiscard=True, operations=[1], playerNames=["private-name"], token="secret")
        snapshot["lastAction"] = {"name": "ActionDealTile", "seat": 0, "tile": "1p", "token": "secret"}
        snapshot["rivers"][0].append({"tile": "1z", "step": 1, "accountId": "private"})
        rows = []
        for serial, action in enumerate(("discard", "kita"), 1):
            rows.extend([{"kind": "turn", "session": "private-session", "serial": serial, "state": snapshot},
                         {"kind": "advice", "adviceKey": f"private-session:{serial}",
                          "advice": {"status": "ready", "best": {"action": action}}}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows))
            ordinary = log_export.log_cases(path)
            all_windows = log_export.log_cases(path, all_discard_windows=True)
        self.assertEqual(len(ordinary), 1)
        self.assertEqual(len(all_windows), 2)
        self.assertNotIn("private", json.dumps(all_windows))
        self.assertNotIn("secret", json.dumps(all_windows))

    def test_ranked_log_export_keeps_strategy_context_without_account_metadata(self):
        snapshot = comparison.load_cases(comparison.FIXTURES)[0]['state'].copy()
        snapshot['match'] = {'source': 'auth-game', 'category': 2, 'modeId': 12,
                             'room': 4, 'levelId': 10401, 'levelIds': [10401] * 4,
                             'playerCount': 4, 'roundCount': 2, 'accountId': 'private'}
        exported = log_export.public_state(snapshot)
        self.assertEqual(exported['match']['levelId'], 10401)
        self.assertEqual(exported['match']['roundCount'], 2)
        self.assertNotIn('accountId', exported['match'])

    @unittest.skipIf(getattr(sys, "frozen", False), "requires a Python CLI subprocess")
    def test_budget_timeouts_are_reported_instead_of_hiding_failed_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "advisor.py").write_text(
                "MODEL = 'timeout-fixture'\n"
                "def advise(state):\n"
                "    return {'status': 'unavailable', 'message': '前瞻计算超过时间预算', "
                "'candidates': [], 'best': None}\n")
            result = comparison.run_version(source, [{"id": "timeout", "state": {}, "expectedStatus": "ready"}],
                                            warmups=1, repeats=2)
        self.assertEqual(result["timeoutCount"], 2)
        self.assertEqual(result["warmupTimeoutCount"], 1)
        self.assertEqual(result["warmupTimeouts"], {"timeout": 1})
        self.assertEqual(result["cases"]["timeout"]["timeoutCount"], 2)
        self.assertEqual(result["latency"]["count"], 2)

    def test_comparison_checks_prefix_order_and_all_candidate_accounts(self):
        first = {"actionId": "a", "score": 1}
        second = {"actionId": "b", "score": 1}
        third = {"actionId": "c", "score": 0}
        fourth = {"actionId": "d", "score": 0}
        advice = {"status": "ready", "best": first,
                  "candidates": [first, second, third, fourth]}
        baseline = {"cases": {"case": {"advice": advice}}}
        current = deepcopy(baseline)
        actual = current["cases"]["case"]["advice"]
        actual["rankedCandidateCount"] = 2
        actual["candidates"] = [first, second, fourth, third]
        change = comparison.compare_cases(baseline, current)["case"]
        self.assertFalse(change["rankedPrefixChanged"])
        self.assertEqual(change["candidateChanges"], [])
        actual["candidates"] = [second, first, fourth, {**third, "score": -1}]
        change = comparison.compare_cases(baseline, current)["case"]
        self.assertTrue(change["rankedPrefixChanged"])
        self.assertEqual(change["candidateChanges"][0]["actionId"], "c")

    @unittest.skipIf(getattr(sys, "frozen", False), "requires a Python CLI subprocess, not the frozen App executable")
    def test_native_accounts_are_distinct_from_derived_residuals(self):
        cases = comparison.load_cases(comparison.FIXTURES, ["closed-tsumo-only-tenpai"])
        report = comparison.run_version(ROOT / "src", cases, warmups=0, repeats=1, include_internal=True)
        item = report["cases"][cases[0]["id"]]
        for candidate in item["advice"]["candidates"]:
            self.assertEqual(item["nativeScoreBreakdowns"][candidate["actionId"]], candidate["scoreBreakdown"])
            self.assertNotIn("residual", candidate["scoreBreakdown"])
            self.assertIn("residual", item["scoreComponents"][candidate["actionId"]])
            internal = item["internalCandidates"][candidate["actionId"]]
            self.assertIn("_rawScore", internal)
            self.assertAlmostEqual(internal["_outcome"]["win"], candidate["terminalProbabilities"]["selfWin"])

    @unittest.skipIf(getattr(sys, "frozen", False), "requires a Python CLI subprocess")
    def test_ranked_prefix_keeps_internal_accounts_for_unranked_tail(self):
        cases = comparison.load_cases(comparison.FIXTURES, ["closed-tsumo-only-tenpai"])
        full = comparison.run_version(ROOT / "src", cases, warmups=0, repeats=1, include_internal=True)
        for limit in (2, 3):
            with self.subTest(limit=limit):
                report = comparison.run_version(ROOT / "src", cases, warmups=0, repeats=1,
                                                include_internal=True, ranked_limit=limit)
                item = report["cases"][cases[0]["id"]]
                candidates = item["advice"]["candidates"]
                self.assertEqual(item["advice"]["rankedCandidateCount"], limit)
                self.assertGreater(len(candidates), limit)
                self.assertEqual(set(item["internalCandidates"]), {c["actionId"] for c in candidates})
                self.assertEqual(item["internalCandidates"], full["cases"][cases[0]["id"]]["internalCandidates"])
                changes = comparison.compare_cases(full, report)[cases[0]["id"]]
                self.assertFalse(changes["rankedPrefixChanged"])
                self.assertEqual(changes["candidateChanges"], [])
                for candidate in candidates:
                    account = item["internalCandidates"][candidate["actionId"]]
                    self.assertAlmostEqual(account["_outcome"]["win"], candidate["terminalProbabilities"]["selfWin"])

    @unittest.skipIf(getattr(sys, "frozen", False), "requires a Git checkout and Python CLI subprocesses")
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
            self.assertFalse(change["rankedPrefixChanged"])
            self.assertEqual(change["candidateChanges"], [])


if __name__ == "__main__":
    unittest.main()
