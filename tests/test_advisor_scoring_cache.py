"""A decision-local scoring cache must preserve exact advice and rule inputs."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles


class ScoringCacheTests(unittest.TestCase):
    def test_full_fixture_advice_equals_uncached_scoring(self):
        path = Path(__file__).parent / "fixtures/advisor_cases.json"
        for case in json.loads(path.read_text())["cases"]:
            with self.subTest(case=case["id"]):
                snapshot = deepcopy(case["state"])
                cached = advisor.advise(snapshot)
                with patch.object(advisor, "_hand_value", side_effect=advisor._score_hand):
                    uncached = advisor.advise(snapshot)
                self.assertEqual(cached["status"], case["expectedStatus"])
                self.assertEqual(uncached["status"], case["expectedStatus"])
                cached.pop("elapsedMs")
                uncached.pop("elapsedMs")
                self.assertEqual(cached, uncached)
                self.assertEqual(snapshot, case["state"])

    def test_every_scoring_input_separates_entries(self):
        hand = tiles("234m234p678s34p55s")
        base = state()
        variants = [("base", hand, "2p", base, False),
                    ("concealed red", tiles("234m234p678s34p05s"), "2p", base, False),
                    ("winning normal five", hand, "5p", base, False),
                    ("winning red five", hand, "0p", base, False),
                    ("tsumo", hand, "2p", base, True)]
        for label, field, value in (("sanma", "playerCount", 3),
                                    ("seat", "selfSeat", 1),
                                    ("replacement", "replacementWin", True),
                                    ("riichi", "riichi", [True] + [False] * 3),
                                    ("double riichi", "doubleRiichi", [True] + [False] * 3),
                                    ("north", "north", [1, 0, 0, 0]),
                                    ("dora", "doras", ["1p"]),
                                    ("deposits", "riichiSticks", 2)):
            variant = deepcopy(base)
            variant[field] = value
            variants.append((label, hand, "2p", variant, False))
        for field in ("ju", "chang", "ben"):
            variant = deepcopy(base)
            variant["round"][field] = 1
            variants.append((field, hand, "2p", variant, False))
        for kind, meld in ((0, "456p"), (0, "406p"), (1, "555p"),
                           (2, "5555p"), (3, "5555p"), (3, "0555p")):
            variant = deepcopy(base)
            variant["melds"][0] = [{"type": kind, "tiles": tiles(meld)}]
            variants.append((f"meld {kind} {meld}", tiles("555z123m789s9p"), "9p", variant, True))
        token = advisor._HAND_VALUES.set({})
        uncached = advisor._score_hand
        try:
            with patch.object(advisor, "_score_hand", wraps=uncached) as score:
                for count, (label, concealed, win, snapshot, tsumo) in enumerate(variants, 1):
                    with self.subTest(input=label):
                        expected = uncached(concealed, win, snapshot, tsumo)
                        self.assertEqual(advisor._hand_value(concealed, win, snapshot, tsumo), expected)
                        self.assertEqual(advisor._hand_value(concealed, win, snapshot, tsumo), expected)
                        self.assertEqual(score.call_count, count)
                with patch.object(advisor.OPTIONS, "has_aka_dora", False):
                    advisor._hand_value(hand, "0p", base, False)
                    self.assertEqual(score.call_count, len(variants) + 1)
        finally:
            advisor._HAND_VALUES.reset(token)

    def test_cached_results_and_errors_do_not_alias(self):
        token = advisor._HAND_VALUES.set({})
        try:
            for hand, win in ((tiles("234m234p678s34p55s"), "2p"), (tiles("123m"), "4p")):
                original = advisor._hand_value(hand, win, state(), False)
                changed = advisor._hand_value(hand, win, state(), False)
                changed["points"] = -1
                if "yaku" in changed:
                    changed["yaku"].append("not a yaku")
                self.assertEqual(advisor._hand_value(hand, win, state(), False), original)
        finally:
            advisor._HAND_VALUES.reset(token)

    def test_completed_red_hand_reuses_winning_family_without_losing_physical_reds(self):
        cases = [
            ("234m340p345p678s55s", "p", []),
            ("111m055p999p333s77z", "p", []),
            ("111m999p333s666s05p", "p", []),
            ("111m055p345p999s22z", "p", []),
            ("123m789s111z05s", "s", [{"type": 2, "tiles": tiles("5555p")}]),
        ]
        for complete_hand, suit, melds in cases:
            with self.subTest(hand=complete_hand):
                snapshot = state()
                snapshot["melds"][0] = melds
                complete = tiles(complete_hand)
                token = advisor._HAND_VALUES.set({})
                reference = advisor._score_hand
                try:
                    with patch.object(advisor, "_score_hand", wraps=reference) as compute:
                        for mode, tsumo in enumerate((False, True), 1):
                            results = []
                            for win in ("0" + suit, "5" + suit):
                                hand = complete.copy()
                                hand.remove(win)
                                expected = reference(hand, win, snapshot, tsumo)
                                results.append(advisor._hand_value(hand, win, snapshot, tsumo))
                                self.assertEqual(results[-1], expected)
                                self.assertGreater(expected["points"], 0)
                            self.assertEqual(results[0], results[1])
                            self.assertEqual(compute.call_count, 2 * mode - 1)
                            plain = ["5" + suit if tile == "0" + suit else tile for tile in complete]
                            plain.remove("5" + suit)
                            expected = reference(plain, "5" + suit, snapshot, tsumo)
                            self.assertEqual(advisor._hand_value(plain, "5" + suit, snapshot, tsumo), expected)
                            self.assertEqual(compute.call_count, 2 * mode)
                        if melds:
                            self.assertEqual(advisor._scoring_tiles(complete, melds)[3], 1)
                finally:
                    advisor._HAND_VALUES.reset(token)

    def test_each_decision_owns_and_releases_its_cache_on_all_exits(self):
        outer = {}
        token = advisor._HAND_VALUES.set(outer)
        seen = []

        def evaluate(snapshot):
            cache = advisor._HAND_VALUES.get()
            self.assertIsNot(cache, outer)
            self.assertEqual(cache, {})
            seen.append(cache)
            advisor._hand_value(tiles("234m234p678s34p55s"), "2p", snapshot, False)
            self.assertTrue(cache)
            return {"status": "ready"}

        try:
            with patch.object(advisor, "_advise", side_effect=evaluate):
                for _ in range(2):
                    self.assertEqual(advisor.advise(state())["status"], "ready")
                    self.assertIs(advisor._HAND_VALUES.get(), outer)
            self.assertIsNot(seen[0], seen[1])
            with patch.object(advisor, "_advise", side_effect=RuntimeError("failed")):
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    advisor.advise(state())
                self.assertIs(advisor._HAND_VALUES.get(), outer)
            self.assertEqual(advisor.advise(state(), cancelled=lambda: True)["status"], "unavailable")
            self.assertIs(advisor._HAND_VALUES.get(), outer)
            self.assertEqual(outer, {})
        finally:
            advisor._HAND_VALUES.reset(token)

    def test_cache_hits_still_check_cancellation_and_budget(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                obsolete = False
                now = 0.
                search_token = advisor._SEARCH.set((1., lambda: obsolete))
                cache_token = advisor._HAND_VALUES.set({})
                try:
                    with patch.object(advisor.time, "monotonic", side_effect=lambda: now):
                        advisor._hand_value(tiles("234m234p678s34p55s"), "2p", state(), False)
                        obsolete, now = cancelled, 2.
                        with self.assertRaises(advisor._SearchStopped):
                            advisor._hand_value(tiles("234m234p678s34p55s"), "2p", state(), False)
                finally:
                    advisor._HAND_VALUES.reset(cache_token)
                    advisor._SEARCH.reset(search_token)


if __name__ == "__main__":
    unittest.main()
