"""Scoring must ignore meld presentation order without losing red identity."""
from copy import deepcopy
from itertools import permutations
import unittest

from advisor import _action_choices, _apply_choice, _hand_value, _scoring_tiles
from test_advisor import state, tiles
from test_advisor_actions import offered


class MeldOrderTests(unittest.TestCase):
    def test_called_low_tile_chi_still_scores_completed_hand(self):
        s = offered("555z123m456p23s99p", 2, ["2s|3s"], "1s")
        before = deepcopy(s)
        after = _apply_choice(s, _action_choices(s)[0][0])
        self.assertEqual(after["melds"][0][0]["tiles"], ["2s", "3s", "1s"])
        hand = after["hand"].copy()
        hand.remove("5z")
        value = _hand_value(hand, "5z", after, True)
        self.assertEqual(value["points"], 1500)
        self.assertIn("Yakuhai (haku)", value["yaku"])
        self.assertEqual(s, before)

    def test_red_chi_pon_and_kans_score_equally_for_every_tile_order(self):
        cases = ((0, ("4p", "0p", "6p"), 0, 2),
                 (1, ("0p", "5p", "5p"), 0, 2),
                 (2, ("0p", "5p", "5p", "5p"), 0, 2),
                 (3, ("0p", "5p", "5p", "5p"), 0, 3),
                 (3, ("5p", "5p", "5p", "5p"), 1, 2))
        hand = tiles("555z123m789s9p")
        for kind, meld_tiles, implicit_red, han in cases:
            reference = None
            for order in sorted(set(permutations(meld_tiles))):
                with self.subTest(kind=kind, order=order):
                    s = state()
                    s["melds"][0] = [{"type": kind, "tiles": list(order)}]
                    before = deepcopy(s)
                    physical, win, _, implicit = _scoring_tiles(hand + ["9p"], s["melds"][0])
                    self.assertEqual(len(set(physical)), len(physical))
                    self.assertEqual(win, physical[len(hand)])
                    self.assertEqual(implicit, implicit_red)
                    value = _hand_value(hand, "9p", s, True)
                    self.assertGreater(value["points"], 0)
                    self.assertEqual(value["han"], han)
                    if reference is None:
                        reference = value
                    self.assertEqual(value, reference)
                    self.assertEqual(s, before)


if __name__ == "__main__":
    unittest.main()
