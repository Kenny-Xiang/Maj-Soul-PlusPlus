"""Exact suit reuse for the pinned mahjong==2.0.0 structural calculator.

The library's private enumerator supplies its original suit decompositions,
including four-copy isolation rules. Only leaf collection is replaced; the
same result formula combines suits. Scoring and physical tile identities do
not use these caches. Library upgrades must pass the reference comparisons.
"""
from functools import lru_cache
from itertools import product

from mahjong.shanten import Shanten, _RegularShanten


class _SuitProfiles(_RegularShanten):
    def __init__(self, suit):
        super().__init__(suit + (0,) * 25)
        self.profiles = {}

    def _update_result(self):
        # Preserve all alternatives instead of updating the library's global
        # minimum, which would stop enumeration at its first complete hand.
        isolated = self._flag_isolated_tiles
        isolation = 0 if not isolated else 1 if not isolated & ~self._flag_four_copies else 2
        paired = bool(self._number_pairs)
        key = self._number_melds, paired, 0 if paired else isolation
        blocks = self._number_tatsu + self._number_pairs
        # With the same melds/head/isolation, extra blocks can only improve or
        # tie the result, including after the four-meld capacity correction.
        self.profiles[key] = max(blocks, self.profiles.get(key, -1))


@lru_cache(maxsize=8192)
def _suit_profiles(suit):
    scan = _SuitProfiles(suit)
    scan._scan(0)
    return tuple((melds, blocks, paired, isolation)
                 for (melds, paired, isolation), blocks in scan.profiles.items())


@lru_cache(maxsize=65536)
def structural_shanten(counts, special):
    total = sum(counts)
    if total > 14 or total % 3 == 0:
        # Retain the authoritative calculator's validation and error text.
        return Shanten.calculate_shanten(counts, use_chiitoitsu=special, use_kokushi=special)
    honors = counts[27:]
    melds = (14 - total) // 3 + sum(n >= 3 for n in honors)
    pairs = sum(n == 2 for n in honors)
    isolation = 2 if 1 in honors else int(4 in honors)
    honor_floor = max(0, sum(n == 4 for n in honors) - int(total % 3 == 2))
    result = 8
    for first, second, third in product(_suit_profiles(counts[:9]),
                                        _suit_profiles(counts[9:18]),
                                        _suit_profiles(counts[18:27])):
        sets = melds + first[0] + second[0] + third[0]
        blocks = pairs + first[1] + second[1] + third[1]
        paired = bool(pairs or first[2] or second[2] or third[2])
        value = 8 - 2 * sets - blocks + max(0, sets + blocks - (5 if paired else 4))
        if not paired and max(isolation, first[3], second[3], third[3]) == 1:
            value += 1
        if value == Shanten.AGARI_STATE:
            return value
        result = min(result, value)
    result = max(result, honor_floor)
    if special and total >= 13:
        result = min(result, Shanten.calculate_shanten_for_chiitoitsu_hand(counts),
                     Shanten.calculate_shanten_for_kokushi_hand(counts))
    return result
