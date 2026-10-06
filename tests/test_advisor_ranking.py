"""Exact ranked prefixes retain full candidate accounting and cancellation."""
from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state
from test_advisor_selection import candidate


class RankedPrefixTests(unittest.TestCase):
    def test_cutoff_preserves_complete_fixed_anchor_groups(self):
        choices = [candidate("first", 300.), candidate("second", 200.),
                   candidate("a", 100. + 1.8e-9, _tieLoss=4.),
                   candidate("b", 100. + .9e-9, _tieLoss=3.),
                   candidate("c", 100., _tieLoss=0.)]
        for order in permutations(choices):
            full = advisor._rank_candidates(order)
            self.assertEqual([c["actionId"] for c in full], ["first", "second", "b", "a", "c"])
            for limit in (1, 2, 3, 4, 5, 10):
                self.assertEqual(advisor._rank_candidates(order, limit=limit), full[:limit])

    def test_cutoff_uses_raw_semantic_metrics_and_all_tied_shapes(self):
        for field, winning, losing in (("_rawScore", 100., 90.), ("_tieLoss", 0., 1.),
                                       ("_tieCurrentLoss", 0., 1.), ("_tieSafeStock", 2., 1.),
                                       ("_tieWin", .2, .1), ("_tieRon", 8., 4.),
                                       ("_tieEfficiency", 450., 400.), ("_tieUkeire", 12.04, 12.01)):
            with self.subTest(field=field):
                choices = [{**candidate(code), field: winning} for code in ("a", "b", "c", "z")]
                choices.extend({**candidate(code), field: losing} for code in ("loser1", "loser2"))
                calls = []

                def shape(item, cache):
                    calls.append(item["actionId"])
                    return 2. if item["actionId"] == "z" else 1.

                with patch.object(advisor, "_same_shanten_improvement", side_effect=shape):
                    full = advisor._rank_candidates(choices)
                    calls.clear()
                    prefix = advisor._rank_candidates(choices, limit=3)
                self.assertEqual(prefix, full[:3])
                self.assertEqual([c["actionId"] for c in prefix], ["z", "a", "b"])
                self.assertEqual(set(calls), {"a", "b", "c", "z"})

    def test_semantic_epsilon_chain_at_cutoff_uses_fixed_anchor(self):
        # Pairwise isclose would incorrectly pull c into the first loss group.
        choices = [candidate("first", 200.), candidate("a", _tieLoss=1., _tieWin=.1),
                   candidate("b", _tieLoss=1. + .9e-9, _tieWin=.2),
                   candidate("c", _tieLoss=1. + 1.8e-9, _tieWin=.9)]
        for order in permutations(choices):
            prefix = advisor._rank_candidates(order, limit=2)
            self.assertEqual([c["actionId"] for c in prefix], ["first", "b"])
            self.assertEqual(prefix, advisor._rank_candidates(order)[:2])

    def test_live_prefix_preserves_all_accounts_explanations_and_raw_metrics(self):
        cases = json.loads((Path(__file__).parent / "fixtures/advisor_cases.json").read_text())["cases"]
        wanted = {"ordinary-efficiency", "confirmed-riichi-furiten", "pon-red-choices", "sanma-kita"}
        logged = json.loads((Path(__file__).parent / "fixtures/advisor_performance_logged_cases.json").read_text())["cases"]
        cases.extend(logged)
        wanted.update(case["id"] for case in logged)
        self.assertTrue(wanted <= {case["id"] for case in cases})
        original_rank = advisor._rank_candidates
        for case in cases:
            if case["id"] not in wanted:
                continue
            with self.subTest(case=case["id"]):
                raw = []

                def capture(candidates, *args, **kwargs):
                    if not kwargs.get("best_only"):
                        raw.append(candidates)
                    return original_rank(candidates, *args, **kwargs)

                snapshot = deepcopy(case["state"])
                with patch.object(advisor, "_rank_candidates", side_effect=capture):
                    full = advisor.advise(snapshot)
                    live = advisor.advise(snapshot, ranked_limit=3)
                self.assertEqual(snapshot, case["state"])
                self.assertEqual(full["status"], "ready")
                self.assertEqual(live.pop("rankedCandidateCount"), min(3, len(full["candidates"])))
                self.assertNotIn("rankedCandidateCount", full)
                self.assertEqual(live["candidates"][:3], full["candidates"][:3])
                for actual, expected in ((live["candidates"], full["candidates"]), (raw[1], raw[0])):
                    self.assertEqual({c["actionId"]: c for c in actual},
                                     {c["actionId"]: c for c in expected})
                for result in (full, live):
                    result.pop("candidates")
                    result.pop("elapsedMs")
                self.assertEqual(live, full)

    def test_limit_covers_all_candidates_without_changing_full_order(self):
        full = advisor.advise(state())
        live = advisor.advise(state(), ranked_limit=100)
        self.assertEqual(live.pop("rankedCandidateCount"), len(full["candidates"]))
        full.pop("elapsedMs")
        live.pop("elapsedMs")
        self.assertEqual(live, full)

    def test_prefix_cancellation_and_deadline_never_publish_partial_candidates(self):
        for interruption in ("cancelled", "deadline"):
            with self.subTest(interruption=interruption):
                choices = [{**candidate(code), "action": "discard", "reasons": []}
                           for code in ("a", "b", "c", "z")]
                stopped = False
                now = 0.

                def shape(item, cache):
                    nonlocal stopped, now
                    stopped = True
                    now = advisor.SEARCH_SECONDS + 1
                    advisor._check_search()
                    return 0.

                with patch.object(advisor, "_discards", return_value=choices), \
                        patch.object(advisor, "_same_shanten_improvement", side_effect=shape), \
                        patch.object(advisor.time, "monotonic", side_effect=lambda: now):
                    result = advisor.advise(state(), ranked_limit=3,
                                            cancelled=(lambda: stopped) if interruption == "cancelled" else None)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["candidates"], [])
                self.assertIsNone(result["best"])
                self.assertIn("撤销" if interruption == "cancelled" else "时间预算", result["message"])
                self.assertEqual(advisor.advise(state(), ranked_limit=3)["status"], "ready")

    def test_public_limit_keeps_two_candidates_for_comparison_explanations(self):
        for invalid in (0, 1, -1, 2.5, True):
            with self.subTest(limit=invalid), self.assertRaises(ValueError):
                advisor.advise(state(), ranked_limit=invalid)


if __name__ == "__main__":
    unittest.main()
