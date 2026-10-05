"""Special-hand completion must retain its actual physical prerequisites."""
import unittest
from unittest.mock import patch

import advisor
from advisor_continuation import finite_policy, leaf_policy
from advisor_routes import seven_pair_targets
from test_advisor import state, tiles


class FiniteSpecialRouteTests(unittest.TestCase):
    def test_seven_pair_targets_retain_pairs_and_require_live_singletons(self):
        counts = advisor.counts34(tiles("11m22p33p44s66s123z"))
        remaining = [0] * 34
        for tile in ("1z", "2z"):
            remaining[advisor.tile_index(tile)] = 3
        targets = seven_pair_targets(counts, remaining)
        self.assertEqual(len(targets), 1)
        _, target = targets[0]
        self.assertEqual(sum(target), 14)
        self.assertEqual(sum(count == 2 for count in target), 7)
        self.assertEqual(target[advisor.tile_index("3z")], 0)
        remaining[advisor.tile_index("2z")] = 0
        self.assertEqual(seven_pair_targets(counts, remaining), [])

    def test_four_copies_do_not_count_as_two_seven_pair_sets(self):
        counts = advisor.counts34(tiles("1111m22p33p44s12z3z"))
        remaining = [0] * 34
        for tile in ("1z", "2z", "3z"):
            remaining[advisor.tile_index(tile)] = 3
        targets = seven_pair_targets(counts, remaining)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][1][advisor.tile_index("1m")], 2)

    def finite(self, hand, remaining, events=(0, 0, 0), river=()):
        s = state(hand + "4m")
        s["rivers"][0] = [{"tile": tile} for tile in river]
        opponents = advisor._opponents(s, remaining, after_current=True, passed_discard="4m")
        with patch.object(advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))), \
                patch.object(advisor, "_danger", return_value=(0., 0., [])), \
                patch.object(advisor, "_policy_risks", return_value=([], [], (0., 0.))):
            result, _ = finite_policy(tiles(hand), s, remaining, opponents, events, "4m")
        self.assertAlmostEqual(result.win + result.deal + result.tsumo + result.other + result.draw, 1.)
        return result

    def test_kokushi_leaf_cannot_replace_an_exhausted_missing_orphan(self):
        hand = "119m19p19s12345z2m"
        s = state(hand + "4m")
        s["rivers"][1] = [{"tile": "6z"}] * 4
        remaining = advisor.unseen_counts(s)
        self.assertEqual(advisor.shanten(advisor.counts34(tiles(hand))), 1)
        self.assertGreater(advisor.shanten(advisor.counts34(tiles(hand)), False), 3)
        self.assertEqual(remaining[advisor.tile_index("6z")], 0)
        result = self.finite(hand, remaining)
        self.assertEqual(result.win, 0.)
        self.assertEqual(result.income, 0.)

    def test_seven_pairs_leaf_cannot_invent_a_seventh_pair(self):
        hand = "11m22p33p44s66s123z"
        remaining = [0] * 34
        remaining[advisor.tile_index("1m")] = 2
        remaining[advisor.tile_index("1z")] = 3
        self.assertEqual(advisor.shanten(advisor.counts34(tiles(hand))), 1)
        self.assertEqual(advisor.shanten(advisor.counts34(tiles(hand)), False), 3)
        result = self.finite(hand, remaining)
        self.assertEqual(result.win, 0.)
        self.assertEqual(result.income, 0.)

    def test_live_seven_pairs_leaf_collects_actual_missing_pairs(self):
        hand = "11m22p33p44s66s123z"
        remaining = [0] * 34
        for tile in ("1m", "1z", "2z"):
            remaining[advisor.tile_index(tile)] = 1
        s = state(hand + "4m")
        with patch.object(advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))), \
                patch.object(advisor, "_policy_risks", return_value=([], [], (0., 0.))):
            outcome = leaf_policy(tiles(hand), s, remaining, [], (0, 0), "4m")
        # Both singleton partners must occur among the two actual draws.
        self.assertAlmostEqual(outcome.win, 1 / 3)
        self.assertGreater(outcome.income, 0.)
        self.assertAlmostEqual(outcome.win + outcome.draw, 1.)

    def test_replacement_leaf_uses_same_physical_seven_pair_contract(self):
        hand = "11m22p33p44s66s123z"
        remaining = [0] * 34
        remaining[advisor.tile_index("1m")] = 2
        remaining[advisor.tile_index("1z")] = 3
        s = state(hand + "4m")
        with patch.object(advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))), \
                patch.object(advisor, "_policy_risks", return_value=([], [], (0., 0.))), \
                patch.object(advisor, "_opportunities", return_value=(0, 0, 0)), \
                patch.object(advisor, "_danger", return_value=(0., 0., [])):
            candidate = advisor._position(tiles(hand), s, remaining, "4m", lookahead_depth=0)
        self.assertEqual(candidate["winProbability"], 0.)

    def test_kokushi_frontier_preserves_whole_wait_furiten(self):
        hand = "119m19p19s12345z2m"
        remaining = [0] * 34
        for tile in ("6z", "7z", "2m"):
            remaining[advisor.tile_index(tile)] = 3
        clear = self.finite(hand, remaining, events=(0, 1, 1))
        furiten = self.finite(hand, remaining, events=(0, 1, 1), river=("6z", "7z"))
        self.assertGreater(clear.win, 0.)
        self.assertEqual(furiten.win, 0.)

    def test_root_kokushi_one_shanten_scores_future_thirteen_sided_wait(self):
        hand = tiles("19m19p19s123456z2m")
        s = state("19m19p19s123456z2m4m")
        remaining = [0] * 34
        remaining[advisor.tile_index("1m")] = 1
        remaining[advisor.tile_index("7z")] = 1
        single = advisor._hand_value(tiles("119m19p19s123456z"), "7z", s, True)["points"]
        double = advisor._hand_value(tiles("19m19p19s1234567z"), "1m", s, True)["points"]
        self.assertEqual(double, 2 * single)
        self.assertEqual(advisor.shanten(advisor.counts34(hand)), 1)
        with patch.object(advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))), \
                patch.object(advisor, "_opportunities", return_value=(0, 0)), \
                patch.object(advisor, "_danger", return_value=(0., 0., [])):
            candidate = advisor._position(hand, s, remaining, "4m")
        # Draw 7z first: discard 2m, then win the thirteen-sided double.
        # Draw 1m first: discard 2m, then win the ordinary single yakuman.
        self.assertEqual(candidate["winProbability"], 1.)
        self.assertEqual(candidate["expectedWinPoints"], (single + double) / 2)


if __name__ == "__main__":
    unittest.main()
