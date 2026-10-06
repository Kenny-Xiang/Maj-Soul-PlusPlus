"""Reused actor configs match fresh scoring across mutable yaku transitions."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles


class EvaluationConfigTests(unittest.TestCase):
    def setUp(self):
        token = advisor._HAND_VALUES.set({})
        self.addCleanup(advisor._HAND_VALUES.reset, token)

    def assert_score_reference(self, hand, win, snapshot, tsumo=False):
        actual = advisor._score_hand(hand, win, snapshot, tsumo)
        with patch.object(advisor, "_evaluation_config", advisor._config):
            expected = advisor._score_hand(hand, win, snapshot, tsumo)
        self.assertEqual(actual, expected)
        return actual

    def test_red_normal_bonus_and_error_transitions_do_not_leak(self):
        snapshot = state()
        hand = tiles("234m234p678s34p55s")
        retained = []
        for concealed, win, indicators in (
                (hand, "0p", ["4p", "4s"]),
                (hand, "5p", []),
                (tiles("123m"), "4p", []),
                (hand, "2p", []),
                (tiles("234m234p678s34p05s"), "0p", ["4s"]),
                (hand, "5p", [])):
            snapshot["doras"] = indicators
            result = self.assert_score_reference(concealed, win, snapshot)
            retained.append((result, deepcopy(result)))
        for result, original in retained:
            self.assertEqual(result, original)
        self.assertIn("error", retained[2][0])
        self.assertGreater(retained[3][0]["points"], 0)
        self.assertEqual(retained[1][0], retained[-1][0])
        self.assertEqual(len(advisor._HAND_VALUES.get()), 1)

    def test_double_yakuman_option_switches_do_not_reuse_downgraded_yaku(self):
        snapshot = state()
        hand = tiles("19m19p19s1234567z")
        values = []
        for enabled in (False, True, False):
            with patch.object(advisor.OPTIONS, "has_double_yakuman", enabled):
                values.append(self.assert_score_reference(hand, "1m", snapshot))
        self.assertEqual(values[0], values[2])
        self.assertEqual(values[1]["points"], values[0]["points"] * 2)
        self.assertEqual(len(advisor._HAND_VALUES.get()), 2)

    def test_projection_and_completed_scoring_can_alternate(self):
        snapshot = state("234m234p678s34p55s")
        hand = snapshot["hand"]
        counts = advisor.counts34(hand)
        for tsumo, win in ((False, "0p"), (True, "5p"), (False, "2p")):
            self.assert_score_reference(hand, win, snapshot, tsumo)
            actual = advisor._uncached_future_value(hand, snapshot, counts, True, tsumo)
            with patch.object(advisor, "_evaluation_config", advisor._config):
                expected = advisor._uncached_future_value(hand, snapshot, counts, True, tsumo)
            self.assertEqual(actual, expected)
            self.assert_score_reference(hand, win, snapshot, tsumo)

    def test_config_inputs_separate_entries_and_plain_configs_stay_fresh(self):
        base = state()
        variants = [(base, False), (base, True)]
        for field, value in (("playerCount", 3), ("selfSeat", 1),
                             ("replacementWin", True), ("riichiSticks", 2),
                             ("riichi", [True, False, False, False]),
                             ("doubleRiichi", [True, False, False, False])):
            changed = deepcopy(base)
            changed[field] = value
            variants.append((changed, False))
        for field in ("ju", "chang", "ben"):
            changed = deepcopy(base)
            changed["round"][field] = 1
            variants.append((changed, False))
        configs = []
        for snapshot, tsumo in variants:
            actual = advisor._evaluation_config(snapshot, tsumo)
            self.assertIs(actual, advisor._evaluation_config(snapshot, tsumo))
            expected = advisor._config(snapshot, tsumo)
            self.assertEqual({k: v for k, v in vars(actual).items() if k != "yaku"},
                             {k: v for k, v in vars(expected).items() if k != "yaku"})
            configs.append(actual)
        self.assertEqual(len({id(config) for config in configs}), len(variants))
        with patch.object(advisor.OPTIONS, "has_aka_dora", False):
            self.assertIsNot(advisor._evaluation_config(base), configs[0])
        self.assertIsNot(advisor._config(base), advisor._config(base))

    def test_opponent_mutation_does_not_change_actor_scoring(self):
        snapshot = state()
        snapshot["round"]["ben"] = 2
        snapshot["riichiSticks"] = 3
        hand = tiles("234m234p678s34p55s")
        before = self.assert_score_reference(hand, "2p", snapshot)
        for seat in (snapshot["selfSeat"], 1):
            config = advisor._config(snapshot, seat=seat)
            config.kyoutaku_number = config.tsumi_number = 0
            config.is_tsumo = True
            config.yaku.tanyao.han_closed = 9
        self.assertEqual(self.assert_score_reference(hand, "2p", snapshot), before)
        config = advisor._evaluation_config(snapshot)
        self.assertEqual((config.kyoutaku_number, config.tsumi_number, config.is_tsumo),
                         (3, 2, False))


if __name__ == "__main__":
    unittest.main()
