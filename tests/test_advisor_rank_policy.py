"""Rank-driven preferences change decisions without inventing match metadata."""
from copy import deepcopy
import unittest

from advisor import _rank_context, _risk_weight, _select_current_policy, Outcome, advise
from test_advisor import state


def ranked(scores, *, level=10401, players=4, mode=12, room=4, winds=2, chang=1, ju=None):
    s = state(players=players)
    s['scores'] = scores
    s['round'].update(chang=chang, ju=players - 1 if ju is None else ju)
    s['match'] = {'source': 'auth-game', 'category': 2, 'modeId': mode, 'room': room,
                  'levelId': level, 'levelIds': [level] * players,
                  'playerCount': players, 'roundCount': winds}
    return s


class RankedPolicyTests(unittest.TestCase):
    def test_close_third_defends_and_last_can_push_same_hand_economics(self):
        third = ranked([20000, 33000, 31000, 16000])
        last = ranked([16000, 33000, 31000, 20000])
        self.assertGreater(_risk_weight(third), 1.15)
        self.assertLess(_risk_weight(last), 1.15)
        attack = Outcome(win=.2, income=1100., deal=.2, loss=1000., draw=.6)
        fold = Outcome(draw=1.)
        self.assertEqual(_select_current_policy(attack, fold, 0., 0., third)[2], 'fold')
        self.assertEqual(_select_current_policy(attack, fold, 0., 0., last)[2], 'attack')

    def test_higher_last_place_penalty_increases_close_third_protection(self):
        s = ranked([20000, 33000, 31000, 16000])
        higher = ranked(s['scores'], level=10503)
        self.assertGreater(_risk_weight(higher), _risk_weight(s))

    def test_final_leader_protects_position_but_deep_last_does_not_gain_low_score_penalty(self):
        self.assertGreater(_risk_weight(ranked([40000, 28000, 20000, 12000])), 1.15)
        last = ranked([7000, 31000, 31000, 31000])
        self.assertLess(_risk_weight(last), 1.15)
        low = ranked([7900, 31000, 31000, 30100])
        high = ranked([8100, 31000, 31000, 29900])
        self.assertLess(abs(_risk_weight(low) - _risk_weight(high)), .05)

    def test_stage_comes_from_match_length_not_round_marker(self):
        late = ranked([20000, 33000, 31000, 16000])
        early = ranked(late['scores'], chang=0, ju=0)
        self.assertGreater(_risk_weight(late), _risk_weight(early))
        self.assertEqual(_rank_context(early)['remainingScheduledHands'], 7)
        self.assertEqual(_rank_context(late)['remainingScheduledHands'], 0)
        extension = ranked(late['scores'], chang=2, ju=0)
        self.assertEqual(_rank_context(extension)['remainingScheduledHands'], 0)

    def test_ties_are_intervals_and_player_order_does_not_change_preference(self):
        s = ranked([20000, 30000, 30000, 20000])
        before = deepcopy(s)
        self.assertEqual(_rank_context(s)['rankRange'], [3, 4])
        swapped = deepcopy(s)
        swapped['scores'] = [30000, 20000, 20000, 30000]
        swapped['selfSeat'] = 1
        self.assertAlmostEqual(_risk_weight(s), _risk_weight(swapped))
        self.assertEqual(s, before)

    def test_sanma_reads_own_three_player_rank(self):
        second = ranked([32000, 43000, 30000], level=20401, players=3, mode=24)
        last = ranked([30000, 43000, 32000], level=20401, players=3, mode=24)
        self.assertGreater(_risk_weight(second), _risk_weight(last))
        self.assertEqual(_rank_context(second)['profile']['placementPoints'], [175, 0, -180])

    def test_unknown_or_inconsistent_metadata_preserves_legacy_policy(self):
        for change in ({'category': 1}, {'modeId': 999}, {'levelId': 20401},
                       {'roundCount': 1}, {'source': 'guess'}, {'playerCount': 3}):
            s = ranked([20000, 33000, 31000, 16000])
            legacy = deepcopy(s)
            legacy.pop('match')
            s['match'].update(change)
            with self.subTest(change=change):
                self.assertEqual(_risk_weight(s), _risk_weight(legacy))
                self.assertNotEqual(_rank_context(s).get('objective'), 'rank-points')

    def test_translation_bounds_and_cached_diagnostics_do_not_leak(self):
        s = ranked([20000, 33000, 31000, 16000])
        shifted = ranked([score + 5000 for score in s['scores']])
        self.assertAlmostEqual(_risk_weight(s), _risk_weight(shifted))
        context = _rank_context(s)
        context['profile']['placementPoints'][0] = 99999
        self.assertEqual(_rank_context(s)['profile']['placementPoints'][0], 125)
        for scores in ([99000, 1000, 0, 0], [1000, 33000, 33000, 33000], [25000] * 4):
            weight = _risk_weight(ranked(scores))
            self.assertGreaterEqual(weight, .75)
            self.assertLessEqual(weight, 1.75)

    def test_sanma_ignores_unused_fourth_seat_and_missing_scores_disable_profile(self):
        s = ranked([32000, 43000, 30000], level=20401, players=3, mode=24)
        weight = _risk_weight(s)
        s['scores'].append(1000000)
        self.assertEqual(_risk_weight(s), weight)
        s['scores'] = []
        self.assertFalse(_rank_context(s)['active'])

    def test_advice_exposes_auditable_rank_preference_and_keeps_point_ledger(self):
        s = ranked([20000, 33000, 31000, 16000])
        s['left'] = 4
        original = deepcopy(s)
        result = advise(s)
        self.assertEqual(result['status'], 'ready', result)
        context = result['rankContext']
        self.assertTrue(context['active'])
        self.assertEqual(context['objective'], 'rank-points')
        self.assertEqual(context['method'], 'bounded-rank-potential')
        self.assertEqual(context['profile']['placementPoints'], [125, 60, -5, -180])
        self.assertEqual(result['riskWeight'], context['riskWeight'])
        self.assertTrue(any('排位' in reason for reason in result['best']['reasons']))
        for c in result['candidates']:
            self.assertAlmostEqual(c['score'], sum(c['scoreBreakdown'].values()))
        self.assertEqual(s, original)


if __name__ == '__main__':
    unittest.main()
