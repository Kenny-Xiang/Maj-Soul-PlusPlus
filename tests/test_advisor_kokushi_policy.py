"""Kokushi prerequisites survive conversion to a terminal outcome ledger."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles


class KokushiPolicyTests(unittest.TestCase):
    def outcome(self, hand, events, remaining, *, risk=0., loss=0., survival=1., river=()):
        s = state(hand + "4m")
        s["rivers"][0] = [{"tile": t} for t in river]
        original = deepcopy(s)
        with patch.object(advisor, "_policy_environment", return_value=(survival, (2000., 0.), (-1000., 1500.))), \
                patch.object(advisor, "_policy_risks", return_value=([], [], (risk, loss))):
            result = advisor._kokushi_outcome(advisor.counts34(tiles(hand)), remaining, [], s, "4m", events, 32000.)
        self.assertEqual(s, original)
        self.assertAlmostEqual(result.win + result.deal + result.tsumo + result.other + result.draw, 1.)
        self.assertAlmostEqual(result.income, result.win * 32000.)
        return result

    def test_two_shanten_requires_three_distinct_missing_orphans(self):
        remaining = [0] * 34
        for tile in ("5z", "6z", "7z"):
            remaining[advisor.tile_index(tile)] = 3
        hand = "119m19p19s1234z23m"
        for events in ((), (0,), (0, 0)):
            self.assertEqual(self.outcome(hand, events, remaining).win, 0.)
        self.assertAlmostEqual(self.outcome(hand, (0, 0, 0), remaining).win, 2 / 9)

    def test_progress_discards_pay_risk_and_endings_do_not_overlap(self):
        remaining = [0] * 34
        remaining[31] = remaining[32] = remaining[33] = 3
        result = self.outcome("119m19p19s1234z23m", (0,), remaining,
                              risk=.2, loss=1000., survival=.75)
        self.assertAlmostEqual(result.deal, .2)
        self.assertAlmostEqual(result.loss, 1000.)
        self.assertAlmostEqual(result.tsumo, .08)
        self.assertAlmostEqual(result.tsumo_loss, 160.)
        self.assertAlmostEqual(result.other, .12)
        self.assertAlmostEqual(result.draw, .6)
        self.assertAlmostEqual(result.draw_income, -600.)

    def test_ready_draw_fee_depends_on_reached_shape(self):
        remaining = [0] * 34
        remaining[33] = 4
        before = self.outcome("119m19p19s12345z2m", (), remaining)
        after = self.outcome("119m19p19s12345z2m", (0,), remaining)
        self.assertEqual(before.draw_income, -1000.)
        self.assertEqual(after.win, 0.)
        self.assertEqual(after.draw_income, 1500.)

    def test_true_wait_furiten_blocks_ron_but_not_tsumo(self):
        remaining = [0] * 34
        remaining[33] = 4
        hand = "119m19p19s123456z"
        self.assertAlmostEqual(self.outcome(hand, (1,), remaining).win, .45)
        self.assertEqual(self.outcome(hand, (1,), remaining, river=("7z",)).win, 0.)
        self.assertEqual(self.outcome(hand, (0,), remaining, river=("7z",)).win, 1.)

    def test_unrelated_orphan_discard_is_not_false_furiten(self):
        remaining = [0] * 34
        remaining[33] = 4
        hand = "119m19p19s123456z"
        self.assertAlmostEqual(self.outcome(hand, (1,), remaining, river=("1z",)).win, .45)

    def test_thirteen_sided_wait_requires_a_pair_and_whole_wait_furiten(self):
        remaining = [0] * 34
        remaining[advisor.tile_index("1m")] = 3
        hand = "19m19p19s1234567z"
        self.assertEqual(self.outcome(hand, (0,), remaining).win, 1.)
        self.assertEqual(self.outcome(hand, (1,), remaining, river=("1z",)).win, 0.)
        self.assertEqual(self.outcome(hand, (), remaining).draw_income, 1500.)

    def test_preserves_old_shape_probability_when_added_discard_risk_is_zero(self):
        for hand in ("119m19p19s1234z23m", "19m19p19s12345z23m"):
            with self.subTest(hand=hand):
                s = state(hand + "4m")
                counts = advisor.counts34(tiles(hand))
                remaining = advisor.unseen_counts(s)
                events = (1, 2, 3, 0) * 4
                with patch.object(advisor, "_event_survival", return_value=.97):
                    expected = advisor._kokushi_probability(counts, remaining, 0, [], s, "4m", 0,
                                                           opportunities=events)
                self.assertAlmostEqual(self.outcome(hand, events, remaining, survival=.97).win, expected)


if __name__ == "__main__":
    unittest.main()
