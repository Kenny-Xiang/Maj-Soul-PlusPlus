"""Concrete route templates preserve physical tiles and exact yaku distance."""
import unittest

import advisor
from advisor_routes import route_targets
from test_advisor import state, tiles


def routes(snapshot):
    hand = snapshot["hand"]
    config = advisor._config(snapshot)
    return route_targets(advisor.counts34(hand), advisor.unseen_counts(snapshot),
                         snapshot["melds"][snapshot["selfSeat"]],
                         (31, 32, 33, config.player_wind, config.round_wind))


def distance(held, target):
    return sum(target) - 1 - sum(min(a, b) for a, b in zip(held, target))


class ConcreteRouteTests(unittest.TestCase):
    def test_target_distances_preserve_toitoi_pair_route(self):
        snapshot = state("888s11s77s45s1z6z", players=3)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles("222p")}]
        for discard in ("7s", "4s", "1z", "6z"):
            with self.subTest(discard=discard):
                after = dict(snapshot, hand=snapshot["hand"].copy())
                after["hand"].remove(discard)
                held = advisor.counts34(after["hand"])
                targets = [target for name, target in routes(after) if name == "toitoi"]
                expected = 3 if discard == "7s" else 2
                self.assertEqual(min(distance(held, target) for target in targets), expected)

    def test_yakuhai_singletons_and_pairs_require_real_tiles(self):
        snapshot = state("456p78s12s55z1z", players=3)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles("222p")}]
        targets = dict(routes(snapshot))
        self.assertIn("yakuhai:31", targets)
        self.assertIn("yakuhai:27", targets)
        self.assertEqual(targets["yakuhai:31"][31], 3)
        self.assertEqual(targets["yakuhai:27"][27], 3)
        snapshot["rivers"][1] = [{"tile": "5z"}, {"tile": "5z"}]
        self.assertNotIn("yakuhai:31", dict(routes(snapshot)))

    def test_existing_sequence_excludes_toitoi_and_all_targets_score(self):
        snapshot = state("456p78s12s55z1z", players=3)
        snapshot["melds"][0] = [{"type": 0, "tiles": tiles("123p")}]
        self.assertFalse(any(name == "toitoi" for name, _ in routes(snapshot)))
        for name, target in routes(snapshot):
            with self.subTest(route=name):
                self.assertEqual(sum(target), 11)
                self.assertEqual(advisor.shanten(target, False), -1)
                complete = [advisor.TILES[i] for i, n in enumerate(target) for _ in range(n)]
                win = complete.pop()
                self.assertGreater(advisor._hand_value(complete, win, snapshot, False)["points"], 0)

    def test_nearest_honor_target_matches_exhaustive_small_hand(self):
        snapshot = state("45s55z1p1z2z", players=3)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s")]
        held = advisor.counts34(snapshot["hand"])
        remaining = advisor.unseen_counts(snapshot)
        available = [a + b for a, b in zip(held, remaining)]
        honor = advisor.tile_index("5z")
        target = dict(routes(snapshot))[f"yakuhai:{honor}"]
        # With two fixed melds and one forced honor set, brute-force the one
        # remaining set and pair to independently verify maximum overlap.
        sets = [tuple([i] * 3) for i in range(34)]
        sets += [tuple(range(i, i + 3)) for i in range(27) if i % 9 < 7]
        best = -1
        for group in sets:
            for pair in range(34):
                trial = [0] * 34
                for index in (*group, pair, pair, honor, honor, honor):
                    trial[index] += 1
                if any(n > available[i] for i, n in enumerate(trial)):
                    continue
                best = max(best, sum(min(a, b) for a, b in zip(held, trial)))
        self.assertEqual(sum(min(a, b) for a, b in zip(held, target)), best)

    def test_sanma_and_fixed_meld_copies_are_never_created(self):
        snapshot = state("888s11s45s", players=3)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s")]
        remaining = advisor.unseen_counts(snapshot)
        held = advisor.counts34(snapshot["hand"])
        fixed = advisor.counts34(t for meld in snapshot["melds"][0] for t in meld["tiles"])
        for _, target in routes(snapshot):
            self.assertEqual(target[1:8], (0,) * 7)
            self.assertEqual(sum(target), 8)
            self.assertTrue(all(n <= h + r and n + f <= 4
                                for n, h, r, f in zip(target, held, remaining, fixed)))
        self.assertEqual(routes(snapshot), routes(snapshot))


class FixedTargetPolicyTests(unittest.TestCase):
    def toy(self, hand, groups, pool, draws, *, risk=0., loss=0., survival=1.):
        from unittest.mock import patch
        from advisor_routes import target_policy

        snapshot = state(hand)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)} for group in groups]
        remaining = advisor.counts34(tiles(pool))
        with patch.object(advisor, "_policy_environment", return_value=(survival, (1000., 500.), (-100., 300.))), \
                patch.object(advisor, "_policy_risks", return_value=([], [], (risk, loss))):
            result, metadata = target_policy(snapshot["hand"], snapshot, remaining, [], (0,) * draws,
                                              targets=[("toitoi", advisor.counts34(tiles("55s")))])
        return result, metadata

    def test_without_replacement_collection_and_ready_draw_fee(self):
        result, metadata = self.toy("5s", ("222p", "777s", "111s", "888s"), "5s11z", 2)
        self.assertAlmostEqual(result.win, 2 / 3)
        self.assertAlmostEqual(result.draw, 1 / 3)
        self.assertAlmostEqual(result.draw_income, 100.)
        self.assertEqual(metadata["routesEvaluated"], 1)
        self.assertEqual(metadata["selected"]["missingTiles"], 1)

    def test_nonwinning_draws_pay_risk_and_terminal_mass_is_one(self):
        result, _ = self.toy("5s", ("222p", "777s", "111s", "888s"), "5s11z", 2,
                             risk=.1, loss=100., survival=.9)
        self.assertAlmostEqual(result.win, 1 / 3 + 2 / 3 * .9 * .9 * .5)
        self.assertGreater(result.loss, 0)
        self.assertGreater(result.tsumo_loss, 0)
        self.assertGreater(result.other_loss, 0)
        self.assertAlmostEqual(result.win + result.deal + result.tsumo + result.other + result.draw, 1.)

    def test_overlapping_identical_targets_are_not_added(self):
        from unittest.mock import patch
        from advisor_routes import target_policy

        snapshot = state("5s")
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s", "111s", "888s")]
        target = advisor.counts34(tiles("55s"))
        with patch.object(advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))), \
                patch.object(advisor, "_policy_risks", return_value=([], [], (0., 0.))):
            result, metadata = target_policy(snapshot["hand"], snapshot, advisor.counts34(tiles("5s11z")),
                                              [], (0,), targets=[("first", target), ("second", target)])
        self.assertAlmostEqual(result.win, 1 / 3)
        self.assertEqual(metadata["routesEvaluated"], 1)

    def test_multi_family_urn_matches_exhaustive_draw_orders(self):
        from itertools import permutations
        from advisor_routes import _target_outcome

        deficits = advisor.counts34(tiles("66z5s"))
        remaining = advisor.counts34(tiles("666z5s11p"))
        physical = tuple(enumerate(tiles("666z5s11p")))
        orders = list(permutations(physical, 3))
        wins = sum(sum(tile == "6z" for _, tile in order) >= 2 and
                   sum(tile == "5s" for _, tile in order) >= 1 for order in orders)
        outcome = _target_outcome(deficits, remaining, (0, 0, 0), 0,
                                  {advisor.tile_index("6z"): 2000., advisor.tile_index("5s"): 2000.},
                                  (0., 0.), 1., (0., 0.), (0., 0.), lambda: None)
        self.assertAlmostEqual(outcome.win, wins / len(orders))
        self.assertAlmostEqual(outcome.income, outcome.win * 2000.)
        self.assertAlmostEqual(outcome.win + outcome.draw, 1.)

    def test_future_red_is_weighted_and_held_red_is_preserved(self):
        from advisor_routes import _target_payments

        snapshot = state("5p")
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s", "111s", "888s")]
        target = advisor.counts34(tiles("55p"))
        deficits = advisor.counts34(tiles("5p"))
        remaining = advisor.counts34(tiles("55p"))
        normal = advisor._hand_value(["5p"], "5p", snapshot, True)["points"]
        red = advisor._hand_value(["0p"], "5p", snapshot, True)["points"]
        payment = _target_payments(snapshot["hand"], snapshot, remaining, target, deficits)[13]
        self.assertEqual(payment, (normal + red) / 2)
        snapshot["hand"] = ["0p"]
        self.assertEqual(_target_payments(snapshot["hand"], snapshot, remaining, target, deficits)[13], red)

    def test_target_score_does_not_keep_discarded_dora_or_red(self):
        from advisor_routes import _target_payments

        snapshot = state("0p")
        snapshot["doras"] = ["4p"]
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s", "111s", "888s")]
        target = advisor.counts34(tiles("11z"))
        remaining = advisor.counts34(tiles("11z"))
        points = _target_payments(snapshot["hand"], snapshot, remaining, target, target)[27]
        actual = advisor._hand_value(["1z"], "1z", snapshot, True)["points"]
        self.assertEqual(points, actual)
        snapshot["hand"] = ["9p"]
        self.assertEqual(_target_payments(snapshot["hand"], snapshot, remaining, target, target)[27], points)

    def test_shared_tail_cache_preserves_renamed_families_and_payments(self):
        from advisor_routes import _target_outcome

        def solve(needed, pool, value):
            deficits = advisor.counts34(tiles(needed))
            return _target_outcome(deficits, advisor.counts34(tiles(pool)), (0, 1, 0, 2, 0), 0,
                                   {i: value for i, n in enumerate(deficits) if n},
                                   (.02, 30.), .98, (1000., 500.), (-100., 300.), lambda: None)

        token = advisor.TABLES.set(None)
        try:
            uncached = solve("66z5s", "666z5s11p", 2000.)
            other_payment = solve("66z5s", "666z5s11p", 8000.)
        finally:
            advisor.TABLES.reset(token)

        token = advisor.TABLES.set({})
        try:
            self.assertEqual(solve("66z5s", "666z5s11p", 2000.), uncached)
            self.assertEqual(solve("55z5s", "555z5s11p", 2000.), uncached)
            self.assertEqual(solve("66z5s", "666z5s11p", 8000.), other_payment)
        finally:
            advisor.TABLES.reset(token)

    def test_target_payment_cache_ignores_unused_tiles_but_checks_cancellation(self):
        from unittest.mock import patch
        from advisor_routes import _target_payments

        snapshot = state("5p1z")
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s", "111s", "888s")]
        target = advisor.counts34(tiles("55p"))
        deficit = advisor.counts34(tiles("5p"))
        token = advisor.TABLES.set({})
        try:
            with patch.object(advisor, "_hand_value", wraps=advisor._hand_value) as scorer, \
                    patch.object(advisor, "_check_search") as check:
                first = _target_payments(["5p"], snapshot, deficit, target, deficit)
                calls = scorer.call_count
                checks = check.call_count
                snapshot["hand"] = tiles("5p2z")
                second = _target_payments(["5p"], snapshot, deficit, target, deficit)
                self.assertEqual(first, second)
                self.assertEqual(scorer.call_count, calls)
                self.assertEqual(check.call_count, checks + 1)
                first[13] = -1.
                self.assertEqual(_target_payments(["5p"], snapshot, deficit, target, deficit), second)
        finally:
            advisor.TABLES.reset(token)

    def test_target_payment_cache_separates_every_scoring_context(self):
        from copy import deepcopy
        from unittest.mock import patch
        from advisor_routes import _target_payments

        snapshot = state("5p")
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s", "111s", "888s")]
        target, deficit = advisor.counts34(tiles("55p")), advisor.counts34(tiles("5p"))
        changed_melds = deepcopy(snapshot["melds"])
        changed_melds[0][0] = {"type": 3, "tiles": tiles("2222p")}
        contexts = (("selfSeat", 1), ("playerCount", 3), ("melds", changed_melds),
                    ("replacementWin", True), ("riichi", [True, False, False, False]),
                    ("doubleRiichi", [True, False, False, False]),
                    ("round", {"chang": 1, "ju": 0, "ben": 0}),
                    ("round", {"chang": 0, "ju": 1, "ben": 0}),
                    ("round", {"chang": 0, "ju": 0, "ben": 1}),
                    ("riichiSticks", 1), ("north", [1, 0, 0, 0]), ("doras", ["4p"]))
        token = advisor.TABLES.set({})
        try:
            with patch.object(advisor, "_hand_value", return_value={"points": 1000.}) as scorer:
                _target_payments(["5p"], snapshot, deficit, target, deficit)
                for field, value in contexts:
                    with self.subTest(field=field, value=value):
                        changed = deepcopy(snapshot)
                        changed[field] = value
                        calls = scorer.call_count
                        _target_payments(["5p"], changed, deficit, target, deficit)
                        self.assertGreater(scorer.call_count, calls)
                calls = scorer.call_count
                with patch.object(advisor.OPTIONS, "has_open_tanyao", False):
                    _target_payments(["5p"], snapshot, deficit, target, deficit)
                self.assertGreater(scorer.call_count, calls)
        finally:
            advisor.TABLES.reset(token)


if __name__ == "__main__":
    unittest.main()
