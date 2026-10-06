"""Finite lookahead properties; recorded discards are not outcome labels."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state


class FiniteRouteTests(unittest.TestCase):
    def test_target_surplus_choices_compare_surviving_income_not_only_loss(self):
        from contextlib import ExitStack
        import advisor_continuation as continuation

        snapshot = state('1245m')
        snapshot['melds'][0] = [{'type': 1, 'tiles': [tile] * 3} for tile in ('2p', '7s', '8s')]
        remaining = advisor.counts34(['3m'])
        target = advisor.counts34(['5z'] * 3 + ['6z'] * 2)
        # Isolate grouping of equivalent surplus discards: the supplied tail
        # is worth 10000. A cheaper but more likely current hit destroys more
        # future income, so minimum current loss alone cannot choose a tile.
        fixed = {'_policy_environment': (1., (0., 0.), (0., 0.)),
                 '_policy_risks': ([], [], (0., 0.)), '_future_value': (0., 0.),
                 '_draw_pool': [('3m', 1)], '_improvements': [], 'shanten': 2,
                 '_risk_weight': 1.}

        def danger(tile, *args):
            return {'1m': (.1, 1000., []), '2m': (.2, 500., [])}.get(tile, (.5, 5000., []))

        with ExitStack() as stack:
            for name, value in fixed.items():
                stack.enter_context(patch.object(advisor, name, return_value=value))
            stack.enter_context(patch.object(advisor, '_danger', side_effect=danger))
            stack.enter_context(patch.object(continuation, 'route_targets', return_value=[('toitoi', target)]))
            stack.enter_context(patch.object(continuation, 'leaf_policy', return_value=advisor.Outcome(draw=1.)))
            target_tail = stack.enter_context(patch.object(
                continuation, 'target_policy', return_value=(advisor.Outcome(win=1., income=10000.),
                                                            {'selected': {'route': 'toitoi'}})))
            outcome, detail = continuation.finite_policy(snapshot['hand'], snapshot, remaining, [], (0, 0))
        self.assertEqual(detail['yakuRoutes']['selected']['discard'], '1m')
        self.assertEqual(outcome.utility(1.), 8000.)
        self.assertEqual(outcome.win, .9)
        self.assertEqual(outcome.loss, 1000.)
        self.assertEqual(target_tail.call_count, 1)

    def test_real_progress_mass_is_not_capped_at_32(self):
        s = state()
        rem = advisor.unseen_counts(s)
        with patch.object(advisor, '_policy_risks', return_value=([], [], (0., 0.))), patch.object(
                advisor, '_policy_environment', return_value=(1., (0., 0.), (0., 0.))):
            values = [advisor._coarse_policy(s['hand'], s, rem, [], (0, 0, 0, 0),
                      3, n, 1000., 1., ron=(0., 0.)) for n in (35, 44)]
        self.assertGreater(values[1].win, values[0].win)

    def test_unknown_open_yaku_does_not_receive_a_probability_prior(self):
        s = state('459p78s12s55z1z', players=3)
        s['melds'][0] = [{'type': 0, 'tiles': ['1p', '2p', '3p']}]
        for tsumo in (False, True):
            self.assertEqual(advisor._future_value(s['hand'], s, advisor.counts34(s['hand']),
                                                   False, tsumo=tsumo)[1], 0.)

    def test_logged_candidates_expand_same_shanten_changes_in_main_estimate(self):
        from advisor_continuation import finite_policy
        cases = json.loads((Path(__file__).parent / 'fixtures/advisor_route_cases.json').read_text())['cases']
        s = next(c['state'] for c in cases if c['id'].startswith('route-297-'))
        rem = advisor.unseen_counts(s)
        hand = s['hand'].copy()
        hand.remove('1z')
        opponents = advisor._opponents(s, rem, after_current=True, passed_discard='1z')
        outcome, detail = finite_policy(hand, s, rem, opponents,
                                        advisor._opportunities(s, after_discard=True), '1z')
        self.assertGreater(detail['sameShantenChangeMass'], 0.)
        self.assertGreater(detail['expectedNextUkeire'], detail['unchangedNextUkeire'])
        self.assertAlmostEqual(outcome.win + outcome.deal + outcome.tsumo + outcome.other + outcome.draw, 1.)


class LoggedRouteProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = json.loads((Path(__file__).parent / 'fixtures/advisor_route_cases.json').read_text())['cases']
        cls.results = {}
        for serial in (1329, 297, 561, 590, 640, 572, 1007):
            snapshot = next(c['state'] for c in cases if c['id'].startswith(f'route-{serial}-'))
            result = advisor.advise(snapshot)
            if result['status'] != 'ready':
                raise AssertionError(result)
            cls.results[serial] = result

    def candidate(self, serial, tile):
        return next(c for c in self.results[serial]['candidates'] if c['tile'] == tile)

    def test_wide_progress_and_shape_improvement_change_receipts_not_bonus(self):
        for serial, preserve, break_shape in ((1329, '1z', '7p'), (297, '1z', '5p'), (561, '1z', '3p')):
            with self.subTest(serial=serial):
                kept = self.candidate(serial, preserve)
                broken = self.candidate(serial, break_shape)
                self.assertGreater(kept['scoreBreakdown'].get('winIncome', 0.),
                                   broken['scoreBreakdown'].get('winIncome', 0.))
                self.assertNotIn('efficiencyReward', kept['scoreBreakdown'])
        self.assertEqual(self.candidate(1329, '1z')['ukeire'], 44)
        self.assertEqual(self.candidate(1329, '7p')['ukeire'], 35)
        # Serial297 has fewer immediate effective tiles; its advantage needs
        # the concrete non-progressing first draws, not an uncapping patch.
        self.assertLess(self.candidate(297, '1z')['ukeire'], self.candidate(297, '5p')['ukeire'])
        self.assertGreater(self.candidate(297, '1z')['finiteLookahead']['sameShantenChangeMass'], 0.)

    def test_all_nonready_candidates_finish_the_same_frontier(self):
        for serial in (1329, 297, 561):
            candidates = self.results[serial]['candidates']
            counts = {c['finiteLookahead']['drawVariants'] for c in candidates}
            self.assertEqual(len(counts), 1)
            self.assertGreater(next(iter(counts)), 0)
            self.assertTrue(all(c['finiteLookahead']['ownDrawDepth'] == 1 for c in candidates))
            for candidate in candidates:
                self.assertAlmostEqual(sum(candidate['terminalProbabilities'].values()), 1.)
                self.assertAlmostEqual(sum(candidate['scoreBreakdown'].values()), candidate['score'])

    def test_two_value_honors_preserve_disjoint_draw_conditioned_routes(self):
        kept = self.candidate(590, '5p')
        single = self.candidate(590, '1z')
        self.assertLess(kept['ukeire'], single['ukeire'])
        self.assertGreater(kept['winProbability'], single['winProbability'])
        self.assertGreater(kept['scoreBreakdown']['winIncome'], single['scoreBreakdown']['winIncome'])
        routes = kept['yakuRoutes']
        self.assertTrue(routes['chosen'])
        self.assertTrue(routes['drawContingent'])
        self.assertGreater(len({r['route'] for r in routes['routes']}), 1)
        self.assertLessEqual(sum(r['drawMass'] for r in routes['routes']), 1.)

    def test_retreat_does_not_get_unknown_yaku_income(self):
        retreat = self.candidate(640, '7s')
        progress = self.candidate(640, '1z')
        self.assertGreater(retreat['shanten'], progress['shanten'])
        self.assertEqual(retreat['yakuConfidence'], 0.)
        self.assertEqual(retreat['winProbability'], 0.)
        self.assertNotIn('winIncome', retreat['scoreBreakdown'])
        # A no-yaku structural draw payment is still legal; it is not a win.
        self.assertGreater(progress['expectedDrawPayment'], 0.)

    def test_call_and_pass_do_not_share_an_unknown_ron_prior(self):
        result = self.results[572]
        call = next(c for c in result['candidates'] if c['action'] == 'pon')
        passed = next(c for c in result['candidates'] if c['action'] == 'pass')
        self.assertTrue(call['yakuRoutes']['drawContingent'])
        self.assertEqual(call['yakuRoutes']['winModes'], 'tsumo-only')
        self.assertLess(call['winProbability'], passed['winProbability'])
        self.assertLess(call['score'], passed['score'])

    def test_early_genbutsu_still_beats_unsafe_honor(self):
        safe = self.candidate(1007, '7s')
        honor = self.candidate(1007, '3z')
        # Genbutsu is safe against the declaring player, not every opponent.
        riichi_risk = next(r for r in safe['opponentRisks'] if r['seat'] == 0)
        self.assertEqual(riichi_risk['probability'], 0.)
        self.assertEqual(riichi_risk['reason'], '现物')
        self.assertGreater(honor['expectedDealInLoss'], safe['expectedDealInLoss'])
        self.assertGreater(safe['score'], honor['score'])
        self.assertEqual(self.results[1007]['best']['tile'], safe['tile'])


if __name__ == '__main__':
    unittest.main()
