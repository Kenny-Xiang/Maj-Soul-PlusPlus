"""Risk reuse preserves physical stock, public safety and complete advice."""
from copy import deepcopy
from itertools import combinations
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles


class DangerCacheTests(unittest.TestCase):
    def setUp(self):
        token = advisor._POLICY_RISKS.set({})
        self.addCleanup(advisor._POLICY_RISKS.reset, token)

    def test_every_tile_and_safe_subset_matches_uncached_risk(self):
        for players in (3, 4):
            advisor._POLICY_RISKS.get().clear()
            snapshot = state("123p456p789s45s11z0p", players)
            snapshot["riichi"][1] = True
            remaining = advisor.unseen_counts(snapshot)
            opponents = advisor._opponents(snapshot, remaining)
            for tile in (*advisor.TILES, "0m", "0p", "0s"):
                index = advisor.tile_index(tile)
                relevant = {index}
                if index < 27:
                    relevant.update(i for i in (index - 3, index + 3)
                                    if 0 <= i < 27 and i // 9 == index // 9)
                unrelated = [i for i in (27, 28, 29, 30) if i not in relevant][:2]
                possible = sorted(relevant) + unrelated
                for size in range(len(possible) + 1):
                    for selected in combinations(possible, size):
                        changed = [{**o, "safe": set(selected) if i == 0 else o["safe"]}
                                   for i, o in enumerate(opponents)]
                        for chankan in (False, True):
                            with self.subTest(players=players, tile=tile, safe=selected,
                                              chankan=chankan):
                                self.assertEqual(
                                    advisor._danger(tile, remaining, changed, chankan=chankan),
                                    advisor._uncached_danger(tile, remaining, changed, chankan=chankan))

    def test_unrelated_safety_and_incomplete_middle_suji_share_computation(self):
        snapshot = state()
        snapshot["riichi"][1] = True
        remaining = advisor.unseen_counts(snapshot)
        opponent = advisor._opponents(snapshot, remaining)[0]
        uncached = advisor._uncached_danger
        with patch.object(advisor, "_uncached_danger", wraps=uncached) as compute:
            values = []
            for safe in ((), ("2p",), ("8p",), ("1z", "7z"), ("2p", "8p"), ("5p",)):
                enemies = [{**opponent, "safe": {advisor.tile_index(t) for t in safe}}]
                values.append(advisor._danger("5p", remaining, enemies))
                self.assertEqual(values[-1], uncached("5p", remaining, enemies))
            self.assertEqual(compute.call_count, 3)
            self.assertTrue(all(value == values[0] for value in values[:4]))
            self.assertGreater(values[0][0], values[4][0])
            self.assertEqual(values[5][0], 0.)

    def test_remaining_stock_red_identity_and_readiness_stay_distinct(self):
        for players in (3, 4):
            advisor._POLICY_RISKS.get().clear()
            snapshot = state("123p456p789s45s11z0p", players)
            snapshot["melds"][1] = [{"type": 1, "tiles": tiles(group)}
                                     for group in ("111p", "222s", "333s", "555z")]
            remaining = advisor.unseen_counts(snapshot)
            opponents = advisor._opponents(snapshot, remaining)
            variants = [remaining]
            for tile in ("5p", "4p", "6z", "1z"):
                depleted = list(remaining)
                depleted[advisor.tile_index(tile)] = 0
                variants.append(tuple(depleted))
            for stock in variants:
                for tile in ("5p", "0p", "1z", "1m"):
                    for readiness in (.25, 1.):
                        enemies = [{**o, "tenpai": readiness} for o in opponents]
                        with self.subTest(players=players, tile=tile, stock=stock,
                                          readiness=readiness):
                            self.assertEqual(advisor._danger(tile, stock, enemies),
                                             advisor._uncached_danger(tile, stock, enemies))
            plain = advisor._danger("5p", remaining, opponents)
            red = advisor._danger("0p", remaining, opponents)
            self.assertGreater(red[1], plain[1])
            self.assertNotEqual(advisor._danger("5p", variants[2], opponents), plain)

    def test_equal_total_stock_preserves_neighbor_and_kokushi_dependencies(self):
        snapshot = state()
        remaining = (2,) * 34
        opponents = advisor._opponents(snapshot, remaining)
        variants = [remaining]
        for blocked, replenished in (("4p", "7z"), ("5p", "6z"), ("1z", "2p")):
            stock = list(remaining)
            stock[advisor.tile_index(blocked)] = 0
            stock[advisor.tile_index(replenished)] = 4
            variants.append(tuple(stock))
        excluded_kokushi = list(variants[-1])
        excluded_kokushi[advisor.tile_index("1m")] = 0
        excluded_kokushi[advisor.tile_index("3p")] = 4
        variants.append(tuple(excluded_kokushi))
        for tile in ("5p", "0p", "1z"):
            for stock in variants:
                self.assertEqual(sum(stock), sum(remaining))
                self.assertEqual(advisor._danger(tile, stock, opponents),
                                 advisor._uncached_danger(tile, stock, opponents))
        self.assertNotEqual(advisor._danger("5p", variants[0], opponents),
                            advisor._danger("5p", variants[1], opponents))
        self.assertNotEqual(advisor._danger("1z", variants[-2], opponents),
                            advisor._danger("1z", variants[-1], opponents))

    def test_full_advice_matches_uncached_risks(self):
        for players in (3, 4):
            snapshot = state("123p456p789s45s11z0p", players)
            snapshot["left"] = 8
            snapshot["riichi"][1] = True
            snapshot["rivers"][1] = [{"tile": t} for t in ("2p", "8p", "1m", "5z")]
            cached = advisor.advise(deepcopy(snapshot))
            with patch.object(advisor, "_danger", advisor._uncached_danger):
                reference = advisor.advise(deepcopy(snapshot))
            self.assertEqual(cached["status"], "ready")
            self.assertEqual(reference["status"], "ready")
            cached.pop("elapsedMs")
            reference.pop("elapsedMs")
            self.assertEqual(cached, reference)

    def test_reused_risk_policy_observes_cancellation_and_deadline(self):
        snapshot = state()
        remaining = advisor.unseen_counts(snapshot)
        opponents = advisor._opponents(snapshot, remaining)
        for cancelled in (False, True):
            now, obsolete = 0., False
            search = advisor._SEARCH.set((1., lambda: obsolete))
            try:
                with patch.object(advisor.time, "monotonic", side_effect=lambda: now):
                    advisor._policy_risks((), snapshot, remaining, opponents)
                    now, obsolete = (0., True) if cancelled else (2., False)
                    with self.assertRaises(advisor._SearchStopped):
                        advisor._policy_risks((), snapshot, remaining, opponents)
            finally:
                advisor._SEARCH.reset(search)


if __name__ == "__main__":
    unittest.main()
