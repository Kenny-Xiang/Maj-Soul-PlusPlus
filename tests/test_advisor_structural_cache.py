"""Exact structural symmetry and decision-local projected-value cache bounds."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from mahjong.shanten import Shanten
import advisor
from test_advisor import state, tiles


class StructuralCacheTests(unittest.TestCase):
    def test_honor_symmetry_matches_reference_for_all_supported_shapes(self):
        rng = random.Random(1329)
        hands = [tiles("19m19p19s1234567z"), tiles("1122m3344p5566s7z")]
        pool = [tile for tile in advisor.TILES for _ in range(4)]
        for size in (1, 4, 7, 10, 13, 14):
            hands.extend(rng.sample(pool, size) for _ in range(12))
        for hand in hands:
            counts = advisor.counts34(hand)
            for special in (False, True):
                expected = Shanten.calculate_shanten(counts, use_chiitoitsu=special, use_kokushi=special)
                self.assertEqual(advisor.shanten(counts, special), expected)
                self.assertEqual(advisor.shanten(counts[:27] + counts[27:][::-1], special), expected)

    def test_honor_renaming_shares_geometry_but_not_value(self):
        advisor._structural_shanten.cache_clear()
        counts = advisor.counts34(tiles("123m456p789s111z2z"))
        advisor.shanten(counts)
        before = advisor._structural_shanten.cache_info()
        advisor.shanten(counts[:27] + counts[27:][::-1])
        after = advisor._structural_shanten.cache_info()
        self.assertEqual(after.misses, before.misses)
        self.assertEqual(after.hits, before.hits + 1)
        self.assertEqual(after.maxsize, 65536)
        snapshot = state("123p45p678s111z2s3s", players=3)
        renamed = deepcopy(snapshot)
        renamed["hand"] = ["3z" if tile == "1z" else tile for tile in snapshot["hand"]]
        token = advisor._HAND_VALUES.set({})
        try:
            first = advisor._future_value(snapshot["hand"], snapshot, advisor.counts34(snapshot["hand"]), True)
            second = advisor._future_value(renamed["hand"], renamed, advisor.counts34(renamed["hand"]), True)
            self.assertGreater(first[1], second[1])
        finally:
            advisor._HAND_VALUES.reset(token)

    def test_projection_cache_preserves_physical_tiles_and_scoring_inputs(self):
        base = state("234m234p678s34p55s")
        variants = [(base, False, True), (base, True, True), (base, False, False)]
        for field, value in (("playerCount", 3), ("selfSeat", 1), ("replacementWin", True),
                             ("riichi", [True, False, False, False]),
                             ("doubleRiichi", [True, False, False, False]),
                             ("north", [1, 0, 0, 0]), ("doras", ["1p"]), ("riichiSticks", 2),
                             ("hand", tiles("234m234p678s34p05s"))):
            changed = deepcopy(base)
            changed[field] = value
            variants.append((changed, False, True))
        for field in ("ju", "chang", "ben"):
            changed = deepcopy(base)
            changed["round"][field] = 1
            variants.append((changed, False, True))
        for kind in (0, 1, 2, 3):
            changed = deepcopy(base)
            changed["hand"] = tiles("234m678s34p55s")
            changed["melds"][0] = [{"type": kind, "tiles": tiles("456p" if kind == 0 else
                                                               "555p" if kind == 1 else "5555p")}]
            variants.append((changed, False, True))
        uncached = advisor._uncached_future_value
        token = advisor._HAND_VALUES.set({})
        try:
            with patch.object(advisor, "_uncached_future_value", wraps=uncached) as compute:
                for index, (snapshot, tsumo, special) in enumerate(variants, 1):
                    hand = snapshot["hand"]
                    args = hand, snapshot, advisor.counts34(hand), special, tsumo
                    expected = uncached(*args)
                    self.assertEqual(advisor._future_value(*args), expected)
                    self.assertEqual(advisor._future_value(*args), expected)
                    self.assertEqual(compute.call_count, index)
                with patch.object(advisor.OPTIONS, "has_aka_dora", False):
                    advisor._future_value(base["hand"], base, advisor.counts34(base["hand"]), True)
                    self.assertEqual(compute.call_count, len(variants) + 1)
        finally:
            advisor._HAND_VALUES.reset(token)

    def test_projection_cache_hit_still_checks_cancellation(self):
        snapshot = state()
        cancelled = False
        token = advisor._HAND_VALUES.set({})
        search = advisor._SEARCH.set((float("inf"), lambda: cancelled))
        try:
            args = snapshot["hand"], snapshot, advisor.counts34(snapshot["hand"]), True
            advisor._future_value(*args)
            cancelled = True
            with self.assertRaises(advisor._SearchStopped):
                advisor._future_value(*args)
        finally:
            advisor._SEARCH.reset(search)
            advisor._HAND_VALUES.reset(token)

    def test_representative_advice_equals_identity_preserving_reference(self):
        cases = json.loads((Path(__file__).parent / "fixtures/advisor_route_cases.json").read_text())["cases"]

        @lru_cache(maxsize=65536)
        def reference(counts, special=True):
            return Shanten.calculate_shanten(counts, use_chiitoitsu=special, use_kokushi=special)

        for case in cases:
            if not case["id"].startswith(("route-1329-", "route-297-", "route-1007-")):
                continue
            with self.subTest(case=case["id"]):
                cached = advisor.advise(case["state"])
                with patch.object(advisor, "shanten", reference), patch.object(
                        advisor, "_future_value", advisor._uncached_future_value):
                    original = advisor.advise(case["state"])
                self.assertEqual(cached["status"], "ready")
                self.assertEqual(original["status"], "ready")
                cached.pop("elapsedMs")
                original.pop("elapsedMs")
                self.assertEqual(cached, original)


if __name__ == "__main__":
    unittest.main()
