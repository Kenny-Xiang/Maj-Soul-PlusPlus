"""Explicit final-round preferences without guessing match length or tie order."""
from copy import deepcopy
import unittest

from advisor import _rank_context, _risk_weight
from test_advisor import state


class EndgamePreferenceTests(unittest.TestCase):
    def test_explicit_final_round_protects_unique_leader(self):
        s = state()
        s["scores"] = [28000, 26000, 24000, 22000]
        before = _risk_weight(s)
        s["round"].update(chang=1, ju=3, isFinal=True)
        self.assertAlmostEqual(_risk_weight(s), before + .25)

    def test_close_penultimate_place_prefers_avoiding_last(self):
        for players, scores in ((4, [20000, 32000, 30000, 18000]),
                                (3, [32000, 43000, 30000])):
            with self.subTest(players=players):
                s = state(players=players)
                s["scores"] = scores
                before = _risk_weight(s)
                s["round"].update(chang=1, ju=players - 1, isFinal=True)
                self.assertAlmostEqual(_risk_weight(s), before + .20)

    def test_unique_last_accepts_more_risk_with_dealer_continuation_discount(self):
        s = state()
        s["scores"] = [18000, 30000, 28000, 24000]
        before = _risk_weight(s)
        s["round"].update(chang=1, ju=3, isFinal=True)
        self.assertAlmostEqual(_risk_weight(s), before - .15)
        s["round"]["ju"] = s["selfSeat"]
        self.assertAlmostEqual(_risk_weight(s), before - .075)

    def test_late_round_number_does_not_invent_match_length(self):
        s = state()
        s["scores"] = [28000, 26000, 24000, 22000]
        before = _risk_weight(s)
        for chang in (1, 2, 3):
            s["round"].update(chang=chang, ju=3)
            self.assertEqual(_risk_weight(s), before)
            self.assertEqual(_rank_context(s)["source"], "unknown-match-length")
            self.assertFalse(_rank_context(s)["active"])

    def test_marker_must_be_explicit_boolean_true(self):
        s = state()
        s["scores"] = [28000, 26000, 24000, 22000]
        before = _risk_weight(s)
        for marker in (False, None, 1, "true"):
            with self.subTest(marker=marker):
                s["round"]["isFinal"] = marker
                self.assertEqual(_risk_weight(s), before)
                self.assertFalse(_rank_context(s)["active"])

    def test_ties_remain_rank_intervals_without_seating_assumptions(self):
        for scores, rank_range in (([30000, 30000, 20000, 20000], [1, 2]),
                                   ([20000, 30000, 30000, 20000], [3, 4]),
                                   ([25000] * 4, [1, 4])):
            with self.subTest(scores=scores):
                s = state()
                s["scores"] = scores
                before = _risk_weight(s)
                s["round"]["isFinal"] = True
                context = _rank_context(s)
                self.assertEqual(context["rankRange"], rank_range)
                self.assertEqual(context["objective"], "points")
                self.assertEqual(_risk_weight(s), before)

    def test_last_place_buffer_threshold_and_other_middle_places(self):
        s = state()
        s["scores"] = [22000, 34000, 30000, 14000]
        before = _risk_weight(s)
        s["round"]["isFinal"] = True
        self.assertEqual(_rank_context(s)["gapAboveLast"], 8000)
        self.assertAlmostEqual(_risk_weight(s), before + .2)
        s["scores"] = [22100, 34000, 30000, 13900]
        self.assertEqual(_rank_context(s)["objective"], "points")
        self.assertEqual(_risk_weight(s), before)
        s["scores"] = [30000, 35000, 20000, 15000]
        self.assertEqual(_rank_context(s)["objective"], "points")
        self.assertEqual(_risk_weight(s), before)

    def test_sanma_context_uses_active_seats_and_does_not_mutate_snapshot(self):
        s = state(players=3)
        s["selfSeat"] = 2
        s["scores"] = [41000, 39000, 25000, 0]
        s["round"].update(chang=1, ju=2, isFinal=True)
        original = deepcopy(s)
        context = _rank_context(s)
        self.assertEqual(context["source"], "explicit-round-marker")
        self.assertEqual(context["rankRange"], [3, 3])
        self.assertEqual(context["gapToFirst"], 16000)
        self.assertEqual(context["gapAboveLast"], 0)
        self.assertTrue(context["dealer"])
        self.assertEqual(context["objective"], "escape-last")
        self.assertAlmostEqual(_risk_weight(s), .925)
        self.assertEqual(s, original)

    def test_incomplete_scores_disable_rank_adjustment(self):
        s = state()
        s["scores"] = []
        s["round"]["isFinal"] = True
        self.assertFalse(_rank_context(s)["active"])
        self.assertEqual(_rank_context(s)["source"], "incomplete-scores")
        self.assertEqual(_risk_weight(s), 1.15)


if __name__ == "__main__":
    unittest.main()
