"""Independent MJAI conversion checks for information boundaries and labels."""
from collections import Counter
from copy import deepcopy
import unittest

try:
    import riichienv
    import numpy
except ImportError:
    riichienv = None


WAITING = ['2m', '3m', '4m', '2s', '3s', '4s', '6s', '7s', '8s',
           '4p', '5p', '7p', '7p']


def opening(required, draws, dora='N'):
    """Allocate a physical deck so hidden filler never overcounts visible tiles."""
    pool = Counter({f'{n}{s}': 4 for s in 'mps' for n in range(1, 10)})
    for suit in 'mps':
        pool['5' + suit] = 3
        pool['5' + suit + 'r'] = 1
    pool.update({tile: 4 for tile in ['E', 'S', 'W', 'N', 'P', 'F', 'C']})
    hands = deepcopy(required)
    for tile in [dora] + draws + [tile for hand in hands for tile in hand]:
        pool[tile] -= 1
        assert pool[tile] >= 0, tile
    for hand in hands:
        while len(hand) < 13:
            tile = next(tile for tile, count in pool.items() if count)
            pool[tile] -= 1
            hand.append(tile)
    return [{'type': 'start_game', 'names': ['a', 'b', 'c', 'd']},
            {'type': 'start_kyoku', 'bakaze': 'E', 'kyoku': 1, 'honba': 0,
             'kyotaku': 0, 'oya': 0, 'scores': [25000] * 4,
             'dora_marker': dora, 'tehais': hands}]


def draw(seat, tile):
    return {'type': 'tsumo', 'actor': seat, 'pai': tile}


def discard(seat, tile, tsumogiri=False):
    return {'type': 'dahai', 'actor': seat, 'pai': tile, 'tsumogiri': tsumogiri}


def finish(events):
    return events + [{'type': 'ryukyoku', 'deltas': [0] * 4},
                     {'type': 'end_kyoku'}, {'type': 'end_game'}]


def passed_ron_game(riichi=False):
    events = opening([['E', 'E'], WAITING, ['3p', '6p'], ['F']],
                     ['C', 'C', 'P', 'C', 'C', 'W', 'W', 'S'])
    events += [draw(0, 'C'), discard(0, 'E'), draw(1, 'C')]
    if riichi:
        events += [{'type': 'reach', 'actor': 1}]
    events += [discard(1, 'C', True)]
    if riichi:
        events += [{'type': 'reach_accepted', 'actor': 1}]
    events += [draw(2, 'P'), discard(2, '3p'), draw(3, 'C'), discard(3, 'F'),
               draw(0, 'C'), discard(0, 'E'), draw(1, 'W'), discard(1, 'W', True),
               draw(2, 'W'), discard(2, '6p'), draw(3, 'S'), discard(3, 'S', True)]
    return finish(events)


@unittest.skipIf(riichienv is None, 'install requirements-conversion.txt for MJAI checks')
class MjaiReviewTests(unittest.TestCase):
    def extract(self, events):
        from policy_mjai import extract_game
        return extract_game(events, 'synthetic-review')

    def candidates(self, sample):
        from policy_actions import legal_actions
        return legal_actions(sample['state'])

    def test_reach_and_discard_form_one_exact_action(self):
        events = passed_ron_game(True)
        samples, audit = self.extract(events)
        reach = [s for s in samples if s['seat'] == 1 and s['action']['action'] == 'riichi']
        self.assertEqual(len(reach), 1)
        self.assertEqual(reach[0]['action']['tile'], '7z')
        self.assertTrue(reach[0]['action']['moqie'])
        source_step = events.index(draw(1, 'C'))
        self.assertEqual(reach[0]['state']['lastStep'], source_step)
        self.assertEqual(len([s for s in samples if s['seat'] == 1 and s['state']['lastStep'] == source_step]), 1)
        self.assertFalse(reach[0]['state']['riichi'][1])
        self.assertFalse(reach[0]['state']['riichiPending'][1])

    def test_temporary_ron_pass_clears_on_own_draw_but_riichi_pass_persists(self):
        for locked in (False, True):
            with self.subTest(riichi=locked):
                events = passed_ron_game(locked)
                samples, audit = self.extract(events)
                first = events.index(discard(2, '3p'))
                second = events.index(discard(2, '6p'))
                earlier = [s for s in samples if s['seat'] == 1 and s['state']['lastStep'] == first]
                self.assertEqual(len(earlier), 1)
                self.assertEqual(earlier[0]['action']['action'], 'pass')
                self.assertIn('ron', {a['action'] for a in self.candidates(earlier[0])})
                later = [s for s in samples if s['seat'] == 1 and s['state']['lastStep'] == second]
                if locked:
                    self.assertFalse(later)
                    own_draw = events.index(draw(1, 'W'))
                    # A forced riichi tsumogiri is not a server decision.
                    self.assertFalse([s for s in samples if s['seat'] == 1 and s['state']['lastStep'] == own_draw])
                else:
                    self.assertEqual(len(later), 1)
                    self.assertIn('ron', {a['action'] for a in self.candidates(later[0])})
                    self.assertFalse(later[0]['state']['furiten'])

    def test_competing_pon_does_not_prove_chi_pass(self):
        events = opening([['3p'], WAITING, ['3p', '3p', '6p'], []], ['C', 'P'])
        events += [draw(0, 'C'), discard(0, '3p'),
                   {'type': 'pon', 'actor': 2, 'target': 0, 'pai': '3p', 'consumed': ['3p', '3p']},
                   discard(2, '6p'), draw(3, 'P'), discard(3, 'P', True)]
        samples, audit = self.extract(finish(events))
        self.assertFalse([s for s in samples if s['seat'] == 1 and s['state']['lastStep'] == 3])
        self.assertGreater(audit['excluded'].get('censored_response', 0), 0)
        # Declining the higher-priority ron is provable even though chi pass is censored.
        self.assertFalse([s for s in samples if s['seat'] == 1 and s['state']['lastStep'] == 5])
        self.assertTrue(any(s['action']['action'] == 'pon' for s in samples))

    def test_chi_kuikae_candidates_exclude_called_and_swapped_tile(self):
        events = opening([['1p'], ['1p', '2p', '3p', '4p', '9s'], [], []], ['C'])
        events += [draw(0, 'C'), discard(0, '1p'),
                   {'type': 'chi', 'actor': 1, 'target': 0, 'pai': '1p', 'consumed': ['2p', '3p']},
                   discard(1, '9s')]
        samples, audit = self.extract(finish(events))
        after_call = next(s for s in samples if s['seat'] == 1 and s['state']['lastStep'] == 4)
        discards = {a['tile'] for a in self.candidates(after_call) if a['action'] == 'discard'}
        self.assertNotIn('1p', discards)
        self.assertNotIn('4p', discards)
        self.assertIn('9s', discards)
        invalid = deepcopy(events)
        invalid[-1] = discard(1, '4p')
        bad_samples, bad_audit = self.extract(finish(invalid))
        self.assertFalse([s for s in bad_samples if s['seat'] == 1 and s['state']['lastStep'] == 4])
        self.assertGreater(bad_audit['excluded'].get('label_not_in_reconstructed_mask', 0), 0)

    def test_red_pon_consumption_is_not_collapsed_or_filled_from_the_label(self):
        events = opening([['5p'], ['5p', '5p', '5pr', '9s'], [], []], ['C'])
        events += [draw(0, 'C'), discard(0, '5p'),
                   {'type': 'pon', 'actor': 1, 'target': 0, 'pai': '5p', 'consumed': ['5pr', '5p']},
                   discard(1, '9s')]
        samples, audit = self.extract(finish(events))
        call = next(s for s in samples if s['action']['action'] == 'pon')
        self.assertEqual(sorted(call['action']['consumed']), ['0p', '5p'])
        pons = [a for a in self.candidates(call) if a['action'] == 'pon']
        self.assertEqual({tuple(a['consumed']) for a in pons}, {('0p', '5p'), ('5p', '5p')})

    def test_two_ron_winners_both_use_the_pre_win_window(self):
        events = opening([['3p'], WAITING, WAITING, []], ['C'])
        events += [draw(0, 'C'), discard(0, '3p'),
                   {'type': 'hora', 'actor': 1, 'target': 0},
                   {'type': 'hora', 'actor': 2, 'target': 0},
                   {'type': 'end_kyoku'}, {'type': 'end_game'}]
        samples, audit = self.extract(events)
        winners = [s for s in samples if s['action']['action'] == 'ron']
        self.assertEqual({s['seat'] for s in winners}, {1, 2})
        self.assertTrue(all(s['state']['lastStep'] == 3 for s in winners))
        self.assertTrue(all(s['state']['scores'] == [25000] * 4 for s in winners))

    def test_hidden_hands_names_and_future_outcomes_do_not_change_first_window(self):
        events = passed_ron_game(False)
        baseline, _ = self.extract(events)
        altered = deepcopy(events)
        altered[0]['names'] = ['private-a', 'private-b', 'private-c', 'private-d']
        altered[1]['tehais'][2], altered[1]['tehais'][3] = altered[1]['tehais'][3], altered[1]['tehais'][2]
        # Only replay the same visible prefix; replace all future outcomes.
        altered = altered[:4] + [{'type': 'ryukyoku', 'deltas': [30000, -10000, -10000, -10000]},
                                 {'type': 'end_kyoku'}, {'type': 'end_game', 'scores': [55000, 15000, 15000, 15000]}]
        other, _ = self.extract(altered)
        first = next(s for s in baseline if s['seat'] == 0 and s['state']['lastStep'] == 2)
        second = next(s for s in other if s['seat'] == 0 and s['state']['lastStep'] == 2)
        self.assertEqual(first, second)
        self.assertNotIn('tehais', json_keys(first))
        self.assertNotIn('names', json_keys(first))

    def test_kan_action_is_retained_but_unreconstructed_hand_suffix_is_excluded(self):
        events = opening([['6s'] * 3, [], [], []], ['6s', 'C'], dora='N')
        events += [draw(0, '6s'), {'type': 'ankan', 'actor': 0, 'consumed': ['6s'] * 4},
                   {'type': 'dora', 'dora_marker': 'P'}, draw(0, 'C'), discard(0, 'C', True)]
        samples, audit = self.extract(finish(events))
        self.assertEqual([s['action']['action'] for s in samples], ['ankan'])
        self.assertEqual(audit['excluded']['hand_suffix_after_kan'], 1)


def json_keys(value):
    if isinstance(value, dict):
        return set(value).union(*(json_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(json_keys(item) for item in value))
    return set()
