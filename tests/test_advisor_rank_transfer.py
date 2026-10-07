"""Recipient and payment-size preferences preserve the public cash ledger."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor
from advisor_rank_policy import loss_context, loss_adjustment
from advisor_routes import _target_outcome
from test_advisor import state, tiles
import test_advisor_accounting as accounting
from test_advisor_actions import own_action, get_action
from test_advisor_rank_policy import ranked


def transfer_case():
    path = Path(__file__).parent / 'fixtures/advisor_rank_transfer_cases.json'
    return json.loads(path.read_text())['cases'][0]['state']


class RankTransferTests(unittest.TestCase):
    def test_actual_payment_detects_last_place_crossing_without_changing_cash(self):
        s = transfer_case()
        context = loss_context(s)
        weight = advisor._risk_weight(s)
        to_last = weight * 8000 - loss_adjustment(context, 0, 8000)
        to_first = weight * 12000 - loss_adjustment(context, 2, 12000)
        self.assertGreater(to_last, to_first)
        self.assertGreater(loss_adjustment(context, 2, 12000), 0.)
        self.assertLess(loss_adjustment(context, 0, 8000), 0.)
        for rival in (0, 2):
            for payment in (1000., 4000., 8000., 12000., 48000.):
                effective = weight - loss_adjustment(context, rival, payment) / payment
                self.assertGreaterEqual(effective, .75 - 1e-12)
                self.assertLessEqual(effective, 1.75 + 1e-12)

    def test_public_fixture_changes_recipient_choice_and_preserves_cash_terms(self):
        s = transfer_case()
        original = deepcopy(s)
        with patch.object(advisor, 'loss_adjustment', return_value=0.):
            uniform = advisor.advise(s)
        actual = advisor.advise(s)
        self.assertEqual(uniform['best']['actionId'], 'discard:1z')
        self.assertEqual(actual['best']['actionId'], 'discard:2z')
        old = {c['actionId']: c for c in uniform['candidates']}
        for candidate in actual['candidates']:
            previous = old[candidate['actionId']]
            self.assertEqual(candidate['dealInProbability'], previous['dealInProbability'])
            self.assertEqual(candidate['expectedDealInLoss'], previous['expectedDealInLoss'])
            self.assertEqual(candidate['terminalProbabilities'], previous['terminalProbabilities'])
            accounting.ScoreAccountingTests().assert_ledger(candidate)
        self.assertEqual(actual['rankContext']['lossMethod'], 'bounded-rank-transfer')
        self.assertEqual(s, original)

    def test_score_permutation_separates_cached_preferences_without_changing_risk(self):
        s = transfer_case()
        swapped = deepcopy(s)
        swapped['scores'][0], swapped['scores'][2] = swapped['scores'][2], swapped['scores'][0]
        self.assertEqual(advisor._risk_weight(s), advisor._risk_weight(swapped))
        remaining = advisor.unseen_counts(s)
        token = advisor._POLICY_RISKS.set({})
        try:
            first = advisor._danger('1z', remaining, advisor._opponents(s, remaining))
            second = advisor._danger('1z', remaining, advisor._opponents(swapped, remaining))
            again = advisor._danger('1z', remaining, advisor._opponents(s, remaining))
        finally:
            advisor._POLICY_RISKS.reset(token)
        self.assertEqual(first[:2], second[:2])
        self.assertNotEqual(advisor._rank_loss_adjustment(first[2]), advisor._rank_loss_adjustment(second[2]))
        self.assertEqual(first, again)

    def test_fold_eligibility_and_held_stock_use_the_same_recipient_preference(self):
        s = transfer_case()
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        eligible = advisor._current_fold_eligibility(s, remaining, opponents)
        self.assertTrue(eligible['2z'])
        self.assertFalse(eligible['1z'])
        _, stock, _ = advisor._policy_risks(tiles('12z'), s, remaining, opponents)
        defense, _, _ = advisor._defense_inputs(tiles('12z'), s, remaining, opponents)
        self.assertAlmostEqual(stock[0][1], .065 * 12000)
        self.assertEqual(defense[0], stock[0])

    def test_unknown_metadata_and_saturated_soul_rewards_add_no_preference(self):
        s = transfer_case()
        s['match']['category'] = 1
        self.assertIsNone(loss_context(s))
        self.assertEqual(loss_adjustment(loss_context(s), 0, 8000.), 0.)
        saturated = ranked([1000000, 0, 0, 0], level=10701, mode=16, room=6)
        self.assertEqual(loss_adjustment(loss_context(saturated), 1, 8000.), 0.)
        self.assertEqual(loss_adjustment(loss_context(transfer_case()), 0, 0.), 0.)

    def test_current_and_locked_future_adjustments_are_charged_once(self):
        s = ranked([20000, 33000, 31000, 16000])
        s['riichi'][0] = True
        s['left'] = 3
        continuation = advisor.Outcome(win=.2, income=1000., deal=.1, loss=300.,
                                       draw=.7, rank_adjustment=37.)
        detail = [{'seat': 1, 'probability': .1, 'rankLossAdjustment': -23.}]
        with patch.object(advisor, '_ready_policy', return_value=[continuation]), patch.object(
                advisor, '_danger', return_value=(.1, 123., detail)):
            candidate = advisor._position(tiles('123m123p123s45s77z'), s,
                                          advisor.unseen_counts(s), '1z')
        self.assertAlmostEqual(candidate['scoreBreakdown']['rankOpponentAdjustment'], -23 + .9 * 37)
        self.assertEqual(candidate['_outcome'].loss, 123 + .9 * 300)
        self.assertAlmostEqual(candidate['_rawScore'], candidate['_outcome'].utility(advisor._risk_weight(s)))
        advisor._abort_terminals(candidate)
        self.assertEqual(candidate['_outcome'].rank_adjustment, -23.)
        self.assertEqual(candidate['_outcome'].loss, 123.)

    def test_coarse_kokushi_and_target_tails_keep_preference_with_paid_discards(self):
        environment = (.93, (200., 0.), (-1000., 1500.))
        with patch.object(advisor, '_policy_environment', return_value=environment), patch.object(
                advisor, '_policy_risks', return_value=([], [], (.1, 100., -25.))):
            coarse = advisor._coarse_policy([], {'selfSeat': 0}, [80], [], (0, 1, 0),
                                             2, 18, 3900., .6)
            s = state('119m19p19s1234z234m')
            remaining = advisor.counts34(tiles('555666777z'))
            kokushi = advisor._kokushi_outcome(advisor.counts34(s['hand'][:-1]), remaining, [], s,
                                               '4m', (0, 1, 0), 32000.)
        deficits = advisor.counts34(tiles('55s'))
        remaining = advisor.counts34(tiles('555s111z'))
        payments = tuple(8000. if i == advisor.tile_index('5s') else 0. for i in range(34))
        target = _target_outcome(deficits, remaining, (0, 1, 0), 0, payments,
                                 (.1, 100., -25.), *environment, lambda: None)
        for outcome in (coarse, kokushi, target):
            self.assertGreater(outcome.loss, 0.)
            self.assertAlmostEqual(outcome.rank_adjustment, -.25 * outcome.loss)

    def test_ranked_riichi_and_north_replacement_have_reconcilable_accounts(self):
        variants = [own_action('123m123p123s45s77z1z', 7, ['1z']),
                    own_action('123p123s789s45p77z4z', 11, [], players=3)]
        for s in variants:
            players = s['playerCount']
            s['left'] = players
            s['scores'] = [20000, 33000, 31000, 16000] if players == 4 else [38000, 25000, 40000]
            s['riichi'][1] = True
            s['match'] = {'source': 'auth-game', 'category': 2,
                          'modeId': 12 if players == 4 else 24, 'room': 4,
                          'levelId': 10401 if players == 4 else 20401,
                          'playerCount': players, 'roundCount': 2}
            s['round'].update(chang=1, ju=players - 1)
            action = 'riichi' if players == 4 else 'kita'
            candidate = get_action(s, action)
            self.assertNotEqual(candidate['scoreBreakdown'].get('rankOpponentAdjustment', 0.), 0.)
            accounting.ScoreAccountingTests().assert_ledger(candidate)


if __name__ == '__main__':
    unittest.main()
