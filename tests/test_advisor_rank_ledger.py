"""Rank preferences travel with their own branch, without changing cash losses."""
import unittest

from advisor_policy import Outcome, advance, discard, fold_table, ready_table


class RankLedgerTests(unittest.TestCase):
    def test_discard_and_residual_scale_future_preference_once(self):
        future = Outcome(draw=1., rank_adjustment=30.)
        result = advance(future, .2, 100., .5, (200., 0.), rank_adjustment=-20.)
        self.assertAlmostEqual(result.rank_adjustment, -8.)
        self.assertEqual(result.loss, 100.)
        self.assertAlmostEqual(result.tsumo_loss, 32.)
        self.assertAlmostEqual(result.utility(1.15), -155.)
        self.assertAlmostEqual(sum((result.win, result.deal, result.tsumo, result.other, result.draw)), 1.)
        current = discard(future, .2, 100., rank_adjustment=-20.)
        self.assertAlmostEqual(current.rank_adjustment, 4.)
        self.assertAlmostEqual((current.scale(.5) + current.scale(.5)).rank_adjustment, 4.)

    def test_fold_prices_each_held_discard_only_if_reached(self):
        result = fold_table((0, 0), 0, [(.1, 100., 40.), (.2, 200., -30.)],
                            (0., 0., 0.), 1., (0., 0.), 0., lambda: None)[0][0]
        self.assertAlmostEqual(result.loss, 280.)
        self.assertAlmostEqual(result.rank_adjustment, 13.)
        self.assertAlmostEqual(result.deal, .28)
        self.assertAlmostEqual(result.draw, .72)

    def test_safe_draw_conditioning_scales_preference_with_cash(self):
        result = fold_table((0, 0), 0, [], (.5, 400., 100.), 1.,
                            (0., 0.), 0., lambda: None, safe_draws=(1, 2))[0][0]
        self.assertEqual(result.deal, 1.)
        self.assertEqual(result.loss, 800.)
        self.assertEqual(result.rank_adjustment, 200.)

    def test_locked_ready_hand_only_pays_for_nonwinning_draws(self):
        result = ready_table((0,), 0, (0., 0.),
                             [(.6, 0., .2, 100., -30.), (.4, 1000., 0., 0., 0.)],
                             [], (0., 0., 0.), 1., (0., 0.), (0., 0.),
                             1.15, True, lambda: None)[0]
        self.assertAlmostEqual(result.income, 400.)
        self.assertAlmostEqual(result.loss, 60.)
        self.assertAlmostEqual(result.rank_adjustment, -18.)
        self.assertAlmostEqual(result.deal, .12)
        self.assertAlmostEqual(result.draw, .48)

    def test_future_attack_and_fold_compare_the_same_rank_preference(self):
        def evaluate(adjustment):
            return ready_table((0,), 0, (0., 0.), [(1., 0., .1, 100., adjustment)],
                               [(.1, 50., 0.)], (.1, 100., adjustment), 1.,
                               (0., 0.), (0., 0.), 1., False, lambda: None)[0]
        point_only = evaluate(0.)
        preferred_recipient = evaluate(80.)
        self.assertEqual(point_only.fold, 1.)
        self.assertEqual(point_only.loss, 50.)
        self.assertEqual(preferred_recipient.fold, 0.)
        self.assertEqual(preferred_recipient.loss, 100.)
        self.assertEqual(preferred_recipient.rank_adjustment, 80.)

    def test_legacy_risk_tuples_are_equivalent_to_zero_adjustments(self):
        def evaluate(extended):
            extra = (0.,) if extended else ()
            return ready_table((0, 1, 0), 0, (.1, 100.),
                               [(1., 0., .2, 100.) + extra], [(.1, 80.) + extra],
                               (.2, 100.) + extra, .95, (200., 0.), (-1000., 1000.),
                               1.15, False, lambda: None, safe_draws=(1, 4))
        self.assertEqual(evaluate(False), evaluate(True))


if __name__ == '__main__':
    unittest.main()
