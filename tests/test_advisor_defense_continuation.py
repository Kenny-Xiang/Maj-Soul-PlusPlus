"""Paid defensive continuation, physical safety stock and safe readiness."""
import unittest
from unittest.mock import patch

import advisor
from advisor_policy import TABLES, fold_table, ready_table
from test_advisor import state, tiles


class DefenseContinuationTests(unittest.TestCase):
    def assert_ledger(self, result):
        self.assertAlmostEqual(result.win + result.deal + result.tsumo + result.other + result.draw, 1.)
        self.assertEqual(result.win, 0.)
        self.assertEqual(result.income, 0.)

    def test_safe_draw_preserves_a_physical_stock_tile(self):
        # Two unseen tiles contain exactly one safe draw. Either draw order
        # survives: discard the new safe tile or spend the single held one.
        result = fold_table((0, 0), 0, [(0., 0.)], (.5, 4000.), 1.,
                            (0., 0.), -1000., lambda: None, safe_draws=(1, 2))[0][0]
        self.assertEqual(result.deal, 0.)
        self.assertEqual(result.loss, 0.)
        self.assertEqual(result.draw_income, -1000.)
        self.assert_ledger(result)

    def test_safe_draw_pool_is_depleted_without_replacement(self):
        # One safe unseen tile cannot supply two safe discards.
        result = fold_table((0, 0), 0, [], (.5, 4000.), 1.,
                            (0., 0.), -1000., lambda: None, safe_draws=(1, 2))[0][0]
        self.assertEqual(result.deal, 1.)
        self.assertEqual(result.loss, 8000.)
        self.assert_ledger(result)

    def test_future_fold_does_not_reuse_untracked_prior_safe_draws(self):
        args = ((0, 0, 0), 0, [(0., 0.)], (2 / 3, 16000 / 3), 1.,
                (0., 0.), -1000., lambda: None)
        fresh = fold_table(*args, safe_draws=(1, 3))
        suffix = fold_table(*args, safe_draws=(1, 3), deplete_prefix=True)
        self.assertEqual(suffix[0], fresh[0])
        # A preceding unspecified draw may already have consumed the one
        # safe unseen tile; entering defense cannot assume it remains.
        self.assertEqual(suffix[1][1].deal, 1.)
        self.assertGreater(suffix[1][1].deal, fresh[1][1].deal)

    def test_conditioned_dangerous_draw_does_not_redraw_a_safe_tile(self):
        table = fold_table((0,), 0, [], (.5, 4000.), 1.,
                           (0., 0.), -1000., lambda: None, safe_draws=(1, 2))
        self.assertEqual(table[0][0].deal, .5)
        self.assertEqual(table[0][1].deal, 1.)
        self.assert_ledger(table[0][0])
        self.assert_ledger(table[0][1])

    def test_defensive_tenpai_fee_requires_every_draw_to_preserve_shape(self):
        args = ((0,), 0, [(0., 0.)], (.5, 4000.), 1., (0., 0.), -1000., lambda: None)
        table = fold_table(*args, safe_draws=(1, 2), tenpai_fee=1000.)
        self.assertEqual(table[0][0].draw_income, 0.)
        self.assertEqual(table[0][1].draw_income, -1000.)
        self.assertEqual(table[0][2].draw_income, 1000.)
        for outcome in table[0]:
            self.assert_ledger(outcome)
        # There is only one safe draw: over two turns shape must break.
        outcome = fold_table((0, 0), *args[1:], safe_draws=(1, 2), tenpai_fee=1000.)[0][0]
        self.assertEqual(outcome.draw_income, -1000.)

    def test_no_yaku_furiten_structural_tenpai_can_defend_its_draw_fee(self):
        s = state("456p789s23s55z9m")
        s["melds"][0] = [{"type": 0, "tiles": tiles("123m")}]
        s["rivers"][0] = [{"tile": "1s"}]
        hand = tiles("456p789s23s55z")
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        waits, furiten = advisor._wait_values(hand, advisor.counts34(hand), remaining, s, None, False)
        self.assertTrue(waits)
        self.assertTrue(furiten)
        self.assertTrue(all(w["ronPoints"] == w["tsumoPoints"] == 0 for w in waits))
        risks = ([("4s", 2, 0., 0.)], [(0., 0.)] * len(hand), (0., 0.))
        with patch.object(advisor, "_policy_environment", return_value=(1., (0., 0.), (-1000., 1000.))):
            outcome = advisor._fold_policy(hand, s, remaining, opponents, (0,), risks)[0][0]
        self.assertEqual(outcome.draw_income, 1000.)
        self.assert_ledger(outcome)

    def test_no_own_draws_preserves_ready_fee_and_still_checks_cancellation(self):
        outcome = fold_table((1,), 0, [], (0., 0.), 1., (0., 0.), -1000., lambda: None,
                             tenpai_fee=1000.)[0][0]
        self.assertEqual(outcome.draw_income, 1000.)
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            fold_table((), 0, [], (0., 0.), 1., (0., 0.), -1000.,
                       lambda: (_ for _ in ()).throw(RuntimeError("cancelled")), safe_draws=(1, 2))

    def test_survived_stock_discard_only_clears_riichi_risk(self):
        s = state("11m234p567p345s22z")
        s["riichi"][1] = True
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        before = [{**o, "safe": set(o["safe"])} for o in opponents]
        only_riichi = opponents[:1]
        stock, _, _ = advisor._defense_inputs(tiles("11m"), s, remaining, only_riichi)
        self.assertGreater(stock[0][0], 0.)
        self.assertEqual(stock[1], (0., 0.))
        stock, _, _ = advisor._defense_inputs(tiles("11m"), s, remaining, opponents)
        self.assertGreater(stock[1][0], 0.)
        self.assertLess(stock[1][0], stock[0][0])
        self.assertEqual(opponents, before)

    def test_safe_draws_must_be_safe_against_every_opponent(self):
        s = state()
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        rows = [("1m", 2, 0., 0.), ("2m", 3, .01, 80.)]
        with patch.object(advisor, "_policy_risks", return_value=(rows, [], (.006, 48.))):
            _, _, safe_draws = advisor._defense_inputs([], s, remaining, opponents)
        self.assertEqual(safe_draws, (2, 5))

    def test_safe_ready_branch_keeps_fee_but_risky_fold_gives_it_up(self):
        # No legal wins (e.g. no-yaku/furiten); the safe tsumogiri still
        # preserves structural tenpai. Breaking shape may only claim noten.
        outcome = ready_table((0,), 0, (0., 0.),
                              [(.5, 0., 0., 0.), (.5, 0., 1., 8000.)],
                              [(0., 0.)], (.5, 4000.), 1., (0., 0.),
                              (-1000., 1000.), 1., False, lambda: None,
                              safe_draws=(1, 2))[0]
        self.assertEqual(outcome.deal, 0.)
        self.assertEqual(outcome.fold, .5)
        self.assertEqual(outcome.draw_income, 0.)
        self.assert_ledger(outcome)

    def test_safe_pool_enters_cache_key_and_cancellation_is_checked(self):
        token = TABLES.set({})
        try:
            args = ((0, 0), 0, [(0., 0.)], (.5, 4000.), 1., (0., 0.), -1000.)
            safe = fold_table(*args, lambda: None, safe_draws=(1, 2))[0][0]
            unsafe = fold_table(*args, lambda: None, safe_draws=(0, 2))[0][0]
            self.assertLess(safe.loss, unsafe.loss)
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                fold_table(*args, lambda: (_ for _ in ()).throw(RuntimeError("cancelled")),
                           safe_draws=(1, 2))
        finally:
            TABLES.reset(token)


if __name__ == "__main__":
    unittest.main()
