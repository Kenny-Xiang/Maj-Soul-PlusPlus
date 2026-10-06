"""Suit decomposition reuse stays exact against mahjong's full calculator."""
from itertools import product
import random
import unittest
from unittest.mock import patch

from mahjong.shanten import Shanten
import advisor
from advisor_shanten import _suit_profiles, structural_shanten
from test_advisor import state, tiles


def reference(counts, special=True):
    return Shanten.calculate_shanten(counts, use_chiitoitsu=special, use_kokushi=special)


class SuitCacheTests(unittest.TestCase):
    def assert_reference(self, counts):
        for special in (False, True):
            self.assertEqual(advisor.shanten(counts, special), reference(counts, special),
                             (counts, special))

    def test_random_sanma_and_yonma_at_every_legal_concealed_length(self):
        rng = random.Random(20261006)
        for players in (3, 4):
            pool = [i for i in range(34) for _ in range(4)
                    if players == 4 or not 1 <= i <= 7]
            for size in (1, 2, 4, 5, 7, 8, 10, 11, 13, 14):
                for _ in range(250):
                    counts = [0] * 34
                    for index in rng.sample(pool, size):
                        counts[index] += 1
                    self.assert_reference(tuple(counts))

    def test_dense_suit_shapes_cover_every_occupancy_of_five_families(self):
        for local in product(range(5), repeat=5):
            total = sum(local)
            if total > 14 or total % 3 == 0:
                continue
            for start, families in ((0, (0, 1, 2, 3, 4)),
                                    (9, (0, 2, 4, 6, 8)),
                                    (18, (4, 5, 6, 7, 8))):
                counts = [0] * 34
                for rank, count in zip(families, local):
                    counts[start + rank] = count
                self.assert_reference(tuple(counts))

    def test_quad_isolation_honor_floor_and_special_shapes(self):
        for hand in ("1111m", "1111m2p", "1111m2222p3333s1z",
                     "1111m2222p3333s11z", "1111z", "1111z2z",
                     "1111z2222z3333z4z", "1111z2222z3333z44z",
                     "1111m2345678999m", "11112222333344m",
                     "11m22p33p44s66s11z7z", "11m22p33p44s66s11z77z",
                     "19m19p19s1234567z", "119m19p19s1234567z",
                     "1111m19p19s12345z"):
            with self.subTest(hand=hand):
                self.assert_reference(advisor.counts34(tiles(hand)))

    def test_invalid_lengths_keep_the_library_exception(self):
        for total in (0, 3, 6, 9, 12, 15, 16):
            counts = tuple(min(4, max(0, total - i * 4)) for i in range(34))
            for special in (False, True):
                with self.assertRaises(ValueError) as expected:
                    reference(counts, special)
                with self.assertRaises(ValueError) as actual:
                    advisor.shanten(counts, special)
                self.assertEqual(str(actual.exception), str(expected.exception))

    def test_changed_hand_reuses_unchanged_suits_with_bounded_caches(self):
        structural_shanten.cache_clear()
        _suit_profiles.cache_clear()
        first = advisor.counts34(tiles("123m456p789s111z2z"))
        second = advisor.counts34(tiles("123m457p789s111z2z"))
        self.assertEqual(advisor.shanten(first), reference(first))
        before = _suit_profiles.cache_info()
        self.assertEqual(advisor.shanten(second), reference(second))
        after = _suit_profiles.cache_info()
        self.assertEqual(after.hits, before.hits + 2)
        self.assertEqual(after.misses, before.misses + 1)
        self.assertEqual(after.maxsize, 8192)
        self.assertEqual(structural_shanten.cache_info().maxsize, 65536)

    def test_improvements_and_exhausted_waits_match_physical_reference(self):
        token = advisor.TABLES.set(None)
        try:
            for players, hand in ((3, "119m234p067s1234z"),
                                  (4, "123m456p789s11z23p"),
                                  (4, "1111m2222p3333s1z")):
                snapshot = state(hand, players)
                counts = advisor.counts34(snapshot["hand"])
                remaining = advisor.unseen_counts(snapshot)
                for special in (False, True):
                    actual = advisor._improvements(counts, remaining, special)
                    waits = advisor._structural_waits(counts, special, players)
                    with patch.object(advisor, "shanten", reference):
                        self.assertEqual(actual, advisor._improvements(counts, remaining, special))
                        self.assertEqual(waits, advisor._structural_waits(counts, special, players))
        finally:
            advisor.TABLES.reset(token)


if __name__ == "__main__":
    unittest.main()
