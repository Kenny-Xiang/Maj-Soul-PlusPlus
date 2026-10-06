"""A reused fixed-target result retains stock, scoring and caller isolation."""
from copy import deepcopy
import random
import unittest
from unittest.mock import patch

import advisor
import advisor_routes as routes
from advisor_target_reference import (local_choices as reference_choices,
                                      route_targets as reference_targets, target_outcome as reference_outcome)
from test_advisor import state, tiles


class TargetReuseTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = state("5p")
        self.snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                       for group in ("222p", "777s", "111s", "888s")]
        self.target = advisor.counts34(tiles("55p"))
        self.remaining = advisor.counts34(tiles("555p123s"))
        self.environment = (0.98, (1000., 500.), (-100., 300.))
        token = advisor.TABLES.set({})
        self.addCleanup(advisor.TABLES.reset, token)

    def solve(self, snapshot=None, remaining=None, *, events=(0, 1, 0), average=(.02, 30.),
              environment=None, name="toitoi"):
        snapshot = self.snapshot if snapshot is None else snapshot
        remaining = self.remaining if remaining is None else remaining
        environment = self.environment if environment is None else environment
        with patch.object(advisor, "_policy_environment", return_value=environment):
            return routes.target_policy(snapshot["hand"], snapshot, remaining, [], events,
                                        targets=[(name, self.target)], average=average)

    def reference(self, *args, **kwargs):
        token = advisor.TABLES.set(None)
        try:
            return self.solve(*args, **kwargs)
        finally:
            advisor.TABLES.reset(token)

    def test_surplus_stock_reuses_complete_outcome_and_rebuilds_metadata(self):
        other_stock = advisor.counts34(tiles("555p456s"))
        expected = self.reference(remaining=other_stock)
        with patch.object(routes, "_target_payments", wraps=routes._target_payments) as price, \
                patch.object(routes, "_target_outcome", wraps=routes._target_outcome) as collect:
            first = self.solve()
            self.assertEqual(first, expected)
            first[1]["selected"]["target"][13] = 999
            first[1]["routes"].append({"corrupted": True})
            second = self.solve(remaining=other_stock)
            self.assertEqual(second, expected)
            renamed = self.solve(remaining=other_stock, name="same-template")
            self.assertEqual(renamed[0], second[0])
            self.assertEqual(renamed[1]["selected"]["route"], "same-template")
            self.assertEqual(price.call_count, 1)
            self.assertEqual(collect.call_count, 1)

    def test_target_stock_events_risks_and_environment_remain_distinct(self):
        variants = [
            {},
            {"remaining": advisor.counts34(tiles("55p1234s"))},
            {"remaining": advisor.counts34(tiles("555p1234s"))},
            {"events": (0, 0, 1)},
            {"events": (0,)},
            {"average": (.1, 300.)},
            {"environment": (.8, (1000., 500.), (-100., 300.))},
            {"environment": (.98, (3000., 1500.), (-100., 300.))},
            {"environment": (.98, (1000., 500.), (-500., 900.))},
        ]
        expected = [self.reference(**kwargs) for kwargs in variants]
        for kwargs, result in zip(variants, expected):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.solve(**kwargs), result)

    def test_red_availability_held_identity_and_missing_count_remain_distinct(self):
        snapshots = [deepcopy(self.snapshot) for _ in range(4)]
        snapshots[1]["rivers"][1] = [{"tile": "0p"}]
        snapshots[2]["hand"] = ["0p"]
        snapshots[3]["hand"] = []
        expected = [self.reference(snapshot) for snapshot in snapshots]
        for snapshot, result in zip(snapshots, expected):
            self.assertEqual(self.solve(snapshot), result)
        self.assertGreater(expected[0][0].income, expected[1][0].income)
        self.assertGreater(expected[2][0].income, expected[0][0].income)
        self.assertNotEqual(expected[3][0].win, expected[0][0].win)

    def test_full_outcome_cache_retains_scoring_context_and_recomputes_utility(self):
        changes = [("doras", ["4p"]), ("north", [1, 0, 0, 0]),
                   ("round", {"chang": 0, "ju": 0, "ben": 2}),
                   ("riichiSticks", 3), ("replacementWin", True)]
        snapshots = [deepcopy(self.snapshot)]
        for field, value in changes:
            changed = deepcopy(self.snapshot)
            changed[field] = value
            snapshots.append(changed)
        expected = [self.reference(snapshot) for snapshot in snapshots]
        for snapshot, result in zip(snapshots, expected):
            self.assertEqual(self.solve(snapshot), result)
        with patch.object(advisor, "_risk_weight", return_value=3.):
            self.assertEqual(self.solve(), self.reference())

    def test_context_matches_explicit_precomputation_and_observes_options(self):
        context = routes._scoring_context(self.snapshot)
        expected = self.solve()
        with patch.object(advisor, "_policy_environment", return_value=self.environment), \
                patch.object(routes, "_scoring_context", side_effect=AssertionError("recomputed")):
            actual = routes.target_policy(self.snapshot["hand"], self.snapshot, self.remaining, [],
                                          (0, 1, 0), targets=[("toitoi", self.target)],
                                          average=(.02, 30.), context=context)
        self.assertEqual(actual, expected)
        with patch.object(advisor.OPTIONS, "has_open_tanyao", False):
            self.assertNotEqual(routes._scoring_context(self.snapshot), context)
            self.assertEqual(self.solve(), self.reference())

    def test_cached_result_still_checks_cancellation(self):
        self.solve()
        with patch.object(advisor, "_check_search", side_effect=advisor._SearchStopped("cancelled")):
            with self.assertRaises(advisor._SearchStopped):
                self.solve()

    def test_unique_triplet_tsumo_prices_match_every_original_winning_tile(self):
        cases = [
            ("111m555p999p333s77z", (), ()),
            ("111m555p999p333s77z", (), ("0p",)),
            ("111m555p999p77z", ("333s",), ()),
            ("111m555p77z", ("999p", "333s"), ()),
            ("111z222z333z444z55z", (), ()),
            ("222s444s666s888s66z", (), ()),
            ("222s333s444s666s88s", (), ()),
            ("111p222p333p999s77z", (), ()),
        ]
        token = advisor.TABLES.set(None)
        self.addCleanup(advisor.TABLES.reset, token)
        for hand, groups, reds in cases:
            for players in (3, 4):
                with self.subTest(hand=hand, groups=groups, reds=reds, players=players):
                    snapshot = state("", players)
                    snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)} for group in groups]
                    snapshot["doras"] = ["4p", "6z"]
                    target = advisor.counts34(tiles(hand))
                    args = list(reds), snapshot, target, target, target
                    with patch.object(routes, "_target_triplet_win", return_value=None):
                        expected = routes._target_payments(*args, red_pool=set())
                    actual = routes._target_payments(*args, red_pool=set())
                    self.assertEqual(actual, expected)

    def test_triplet_reuse_keeps_tanki_and_possible_sequences_distinct(self):
        target = advisor.counts34(tiles("111m555m999p333s77z"))
        snapshot = state("")
        cache_token = advisor._HAND_VALUES.set({})
        self.addCleanup(advisor._HAND_VALUES.reset, cache_token)
        with patch.object(advisor, "_score_hand", wraps=advisor._score_hand) as score, \
                patch.object(advisor, "_hand_value", wraps=advisor._hand_value) as value:
            payments = routes._target_payments([], snapshot, target, target, target, red_pool=set())
        self.assertEqual(score.call_count, 2)
        self.assertEqual(value.call_count, 2)
        self.assertEqual(payments[advisor.tile_index("7z")], 2 * payments[0])
        sequence_target = advisor.counts34(tiles("111m222m333m999p77z"))
        self.assertIsNone(routes._target_triplet_win(sequence_target))
        self.assertIsNone(routes._target_triplet_win(advisor.counts34(tiles("11m22m33p44p55s66s77z"))))

    def test_full_triplet_tsumo_prices_include_pair_migration_and_shared_yakuman(self):
        cases = [
            ("111p222p333p44p", ((1, "777z"),), ()),
            ("111p222p333p99p", ((1, "777z"),), ()),
            ("777p888p999p11p", ((1, "111s"),), ()),
            ("333p444p555p66p", ((2, "1111z"),), ("0p",)),
            ("111p222p333p44p", ((3, "7777z"),), ()),
            ("222s333s444s66s", ((1, "666z"),), ()),
            ("111p222p333p444p55p", (), ("0p",)),
            ("111p222p33p", ((1, "777z"), (1, "888s")), ()),
        ]
        token = advisor.TABLES.set(None)
        self.addCleanup(advisor.TABLES.reset, token)
        for hand, groups, reds in cases:
            for players in (3, 4):
                with self.subTest(hand=hand, groups=groups, players=players):
                    snapshot = state("", players)
                    snapshot["melds"][0] = [{"type": kind, "tiles": tiles(group)} for kind, group in groups]
                    snapshot["doras"] = ["2p", "6z"]
                    snapshot["replacementWin"] = True
                    target = advisor.counts34(tiles(hand))
                    args = list(reds), snapshot, target, target, target
                    with patch.object(routes, "_target_triplet_win", return_value=None):
                        expected = routes._target_payments(*args, red_pool=set())
                    self.assertEqual(routes._target_payments(*args, red_pool=set()), expected)

    def test_sequence_sharing_cache_keeps_chi_and_kazoe_rules_separate(self):
        target = advisor.counts34(tiles("111p222p333p44p"))
        self.assertIsNone(routes._target_triplet_win(target, False))
        self.assertEqual(routes._target_triplet_win(target, True), advisor.tile_index("1p"))
        self.assertIsNone(routes._target_triplet_win(target, False))
        token = advisor.TABLES.set(None)
        self.addCleanup(advisor.TABLES.reset, token)
        for kind, group, calls in ((1, "777z", 2), (0, "789s", 4)):
            snapshot = state("")
            snapshot["melds"][0] = [{"type": kind, "tiles": tiles(group)}]
            with patch.object(advisor, "_hand_value", wraps=advisor._hand_value) as value:
                routes._target_payments([], snapshot, target, target, target, red_pool=set())
            self.assertEqual(value.call_count, calls)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles("777z")}]
        with patch.object(advisor.OPTIONS, "kazoe_limit", advisor.HandConfig.KAZOE_SANBAIMAN), \
                patch.object(advisor, "_hand_value", wraps=advisor._hand_value) as value:
            routes._target_payments([], snapshot, target, target, target, red_pool=set())
        self.assertEqual(value.call_count, 4)

    def test_enemy_event_runs_preserve_original_ledger_within_roundoff(self):
        # Frozen outputs from the per-event recursion, including an exhausted
        # urn. Exact counting changes only floating-point evaluation order.
        cases = [
            ("5p1z", "555p11z123s", (1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3),
             (0.16793998711226377, 547.48435798598, 0.05665730685856377, 41.49764907748861,
              0.09930373244652557, 127.10877753155273, 0.14895559866978836, 110.67400981165275,
              0.5271433749128586, 390.9486956853727, 0.0)),
            ("55p1z", "555p11z123s", (0, 1, 2, 3, 0, 2, 1, 3, 0, 1, 2, 3),
             (0.0785180737845129, 235.2663217496621, 0.09288388662618478, 68.0311710153948,
              0.10738578992213399, 137.4538111003315, 0.16107868488320098, 119.68146286821833,
              0.5601335647839674, 245.92104028275298, 0.0)),
            ("55p", "5p1s", (0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3),
             (0.0, 0.0, 0.0686741472092933, 50.29917268572564,
              0.11194899425935906, 143.29471265197958, 0.16792349138903856, 124.76715410205566,
              0.6514533671423091, 593.4740174666437, 0.0)),
        ]
        for needed, pool, events, expected in cases:
            with self.subTest(needed=needed, events=events):
                deficits = advisor.counts34(tiles(needed))
                remaining = advisor.counts34(tiles(pool))
                payments = {i: 1000. + 113 * i for i, n in enumerate(deficits) if n}
                args = (deficits, remaining, events, 0, payments, (.037, 27.1), .971,
                        (1280., 743.), (-331., 911.), lambda: None)
                for _ in range(2):
                    for actual, old in zip(routes._target_outcome(*args), expected):
                        self.assertLess(abs(actual - old), 1e-10)

    def test_enemy_event_run_checks_cancellation_between_events(self):
        calls = 0

        def check():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise advisor._SearchStopped("cancelled")

        deficits = advisor.counts34(tiles("5p"))
        with self.assertRaises(advisor._SearchStopped):
            routes._target_outcome(deficits, self.remaining, (1, 2, 3, 0), 0,
                                   {13: 2000.}, (.02, 30.), .98,
                                   (1000., 500.), (-100., 300.), check)
        self.assertEqual(calls, 3)

    def test_collection_distribution_reuses_shape_across_payment_contexts(self):
        deficits = advisor.counts34(tiles("5p"))
        args = (deficits, self.remaining, (0, 1, 2, 3, 0, 1, 2, 3, 0), 0)
        environment = ((.02, 30.), .98, (1000., 500.), (-100., 300.), lambda: None)
        with patch.object(routes, "_target_distribution", wraps=routes._target_distribution) as distributions:
            first = routes._target_outcome(*args, {13: 2000.}, *environment)
            self.assertEqual(distributions.call_count, 1)
            second = routes._target_outcome(*args, {13: 8000.}, *environment)
            self.assertEqual(distributions.call_count, 1)
        self.assertEqual(first.win, second.win)
        self.assertEqual(second.income, first.income * 4)

    def test_canonical_outcome_reuses_renamed_families_and_checks_cancellation(self):
        events = (0, 1, 0, 2, 0, 1, 0)
        first_args = (advisor.counts34(tiles("5p66z")), advisor.counts34(tiles("555p666z11s")),
                      events, 0, {13: 1000., 32: 3000.}, (.02, 30.), .98,
                      (1000., 500.), (-100., 300.))
        second_args = (advisor.counts34(tiles("4m77z")), advisor.counts34(tiles("444m777z99s")),
                       events, 0, {3: 1000., 33: 3000.}, (.02, 30.), .98,
                       (1000., 500.), (-100., 300.))
        first = routes._target_outcome(*first_args, lambda: None)
        second = routes._target_outcome(*second_args, lambda: None)
        self.assertIs(first, second)
        for args in (first_args, second_args):
            expected = reference_outcome(*args, lambda: None)
            for actual, old in zip(second, expected):
                self.assertLess(abs(actual - old), 1e-10)
        before = advisor.TABLES.get().copy()

        def cancelled():
            raise advisor._SearchStopped("cancelled")

        with self.assertRaises(advisor._SearchStopped):
            routes._target_outcome(*second_args, cancelled)
        self.assertEqual(advisor.TABLES.get(), before)

    def test_canonical_outcome_separates_every_ledger_input(self):
        deficits = advisor.counts34(tiles("5p66z"))
        remaining = advisor.counts34(tiles("555p666z11s"))
        base = (deficits, remaining, (0, 1, 0, 2, 0), 0, {13: 1000., 32: 3000.},
                (.02, 30.), .98, (1000., 500.), (-100., 300.))
        changes = [(0, advisor.counts34(tiles("55p66z"))),
                   (1, advisor.counts34(tiles("55p666z111s"))),
                   (1, advisor.counts34(tiles("555p666z111s"))),
                   (2, (1, 0, 0, 2, 0)), (3, 1), (4, {13: 2000., 32: 3000.}),
                   (5, (.04, 30.)), (5, (.02, 60.)), (6, .96),
                   (7, (2000., 500.)), (7, (1000., 900.)),
                   (8, (-300., 300.)), (8, (-100., 600.))]
        original = routes._target_outcome(*base, lambda: None)
        for index, value in changes:
            changed = list(base)
            changed[index] = value
            with self.subTest(index=index, value=value):
                token = advisor.TABLES.set(None)
                try:
                    expected = routes._target_outcome(*changed, lambda: None)
                finally:
                    advisor.TABLES.reset(token)
                actual = routes._target_outcome(*changed, lambda: None)
                self.assertEqual(actual, expected)
                self.assertIsNot(actual, original)
                self.assertIs(actual, routes._target_outcome(*changed, lambda: None))

    def test_combinatorial_collection_matches_recursive_urn_on_random_small_pools(self):
        rng = random.Random(66172)
        token = advisor.TABLES.set(None)
        self.addCleanup(advisor.TABLES.reset, token)
        for trial in range(200):
            remaining, deficits = [0] * 34, [0] * 34
            for i in range(rng.randint(1, 5)):
                remaining[i] = rng.randint(1, 4)
                deficits[i] = rng.randint(1, remaining[i])
            remaining[20] = rng.randint(0, 8)
            events = tuple(rng.randrange(4) for _ in range(rng.randrange(1, 24)))
            payments = {i: rng.randrange(1, 50) * 100 for i, n in enumerate(deficits) if n}
            average = (rng.choice((0., 1., rng.random() * .1)), rng.random() * 100)
            survival = rng.choice((0., 1., .9 + rng.random() * .1))
            args = (tuple(deficits), tuple(remaining), events, 0, payments, average,
                    survival, (1300., 2700.), (-300., 900.), lambda: None)
            expected = reference_outcome(*args)
            actual = routes._target_outcome(*args)
            with self.subTest(trial=trial):
                for field, old, new in zip(advisor.Outcome._fields, expected, actual):
                    self.assertLess(abs(old - new), 1e-10, field)

    def test_optimal_local_template_bound_keeps_exhaustive_tie_order(self):
        rng = random.Random(87432)
        for suited, width in ((False, 7), (True, 9)):
            for trial in range(24):
                counts = tuple(rng.randrange(4) for _ in range(width))
                available = tuple(min(4, n + rng.randrange(3)) for n in counts)
                groups = trial % 4
                with self.subTest(suited=suited, trial=trial):
                    self.assertEqual(routes._local_choices.__wrapped__(counts, available, groups, suited),
                                     reference_choices(counts, available, groups, suited))

    def test_shared_triplet_order_preserves_every_pair_and_honor_target(self):
        rng = random.Random(37519)
        groups = ("222p", "777s", "111s", "888s")
        for trial in range(24):
            melds = [{"type": 1, "tiles": tiles(group)} for group in groups[:1 + trial % 4]]
            stock = [4] * 34
            for meld in melds:
                for tile in meld["tiles"]:
                    stock[advisor.tile_index(tile)] -= 1
            pool = [i for i, n in enumerate(stock) for _ in range(n)]
            rng.shuffle(pool)
            hand_size = 13 - 3 * len(melds)
            counts = [0] * 34
            for i in pool[:hand_size]:
                counts[i] += 1
            for i in pool[:hand_size + trial]:
                stock[i] -= 1
            honors = (31, 32, 33, 27 + rng.randrange(4), 27 + rng.randrange(4))
            args = tuple(counts), tuple(stock), melds, honors
            with self.subTest(trial=trial):
                self.assertEqual(routes.route_targets(*args), reference_targets(*args))


if __name__ == "__main__":
    unittest.main()
