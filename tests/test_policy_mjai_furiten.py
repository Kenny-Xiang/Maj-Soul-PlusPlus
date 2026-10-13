"""Decision-time furiten uses public prefix, including shape waits without yaku."""
import unittest

from test_policy_mjai_review import WAITING, discard, draw, finish, opening, passed_ron_game, riichienv


def no_yaku_prefix():
    hand = ['2m', '3m', '2p', '3p', '4p', '5s', '6s', '7s', 'E', 'E', '8m', '9m', 'C']
    events = opening([['1m'], hand, ['7m', '8m'], ['E']], ['C', 'P', 'F', 'S', 'C', 'P'])
    return events + [draw(0, 'C'), discard(0, '1m'),
                     {'type': 'chi', 'actor': 1, 'target': 0, 'pai': '1m', 'consumed': ['2m', '3m']},
                     discard(1, 'C'), draw(2, 'P'), discard(2, '7m'),
                     draw(3, 'F'), discard(3, 'E')]


@unittest.skipIf(riichienv is None, 'install requirements-conversion.txt for MJAI checks')
class MjaiFuritenTests(unittest.TestCase):
    def extract(self, events):
        from policy_mjai import extract_game
        return extract_game(events, 'synthetic-furiten')[0]

    def at_step(self, samples, seat, step):
        return [s for s in samples if s['seat'] == seat and s['state']['lastStep'] == step]

    def test_self_discard_furiten_survives_draw_and_clears_after_wait_change(self):
        events = opening([WAITING, [], [], []], ['6p', 'P', 'F', 'S', 'C', 'P', 'F', 'S', 'W'])
        events += [draw(0, '6p'), discard(0, '6p', True)]
        for seat, tile in ((1, 'P'), (2, 'F'), (3, 'S')):
            events += [draw(seat, tile), discard(seat, tile, True)]
        first_step = len(events)
        events += [draw(0, 'C'), discard(0, '4p')]
        for seat, tile in ((1, 'P'), (2, 'F'), (3, 'S')):
            events += [draw(seat, tile), discard(seat, tile, True)]
        second_step = len(events)
        events += [draw(0, 'W'), discard(0, 'W', True)]
        samples = self.extract(finish(events))
        self.assertTrue(self.at_step(samples, 0, first_step)[0]['state']['furiten'])
        self.assertFalse(self.at_step(samples, 0, second_step)[0]['state']['furiten'])

    def test_no_yaku_wait_sets_temporary_furiten_without_a_ron_window(self):
        prefix = no_yaku_prefix()
        own_draw_step = len(prefix) + 2
        samples = self.extract(finish(prefix + [draw(0, 'S'), discard(0, 'S', True),
                                               draw(1, 'C'), discard(1, 'C', True)]))
        self.assertFalse(self.at_step(samples, 1, prefix.index(discard(2, '7m'))))
        later_response = self.at_step(samples, 1, len(prefix) - 1)[0]
        self.assertTrue(later_response['state']['furiten'])
        self.assertEqual(later_response['action']['action'], 'pass')
        self.assertFalse(self.at_step(samples, 1, own_draw_step)[0]['state']['furiten'])

    def test_call_then_own_discard_clears_temporary_furiten(self):
        prefix = no_yaku_prefix()
        events = prefix + [{'type': 'pon', 'actor': 1, 'target': 3, 'pai': 'E', 'consumed': ['E', 'E']},
                           discard(1, '9m'), draw(2, 'P'), discard(2, '8m'),
                           {'type': 'hora', 'actor': 1, 'target': 2},
                           {'type': 'end_kyoku'}, {'type': 'end_game'}]
        samples = self.extract(events)
        self.assertTrue(self.at_step(samples, 1, len(prefix))[0]['state']['furiten'])
        winning = self.at_step(samples, 1, len(prefix) + 3)[0]
        self.assertEqual(winning['action']['action'], 'ron')
        self.assertFalse(winning['state']['furiten'])

    def test_riichi_missed_ron_stays_furiten_on_optional_self_draw(self):
        events = passed_ron_game(True)
        step = events.index(draw(1, 'W'))
        events[step] = draw(1, '6p')
        events[step + 1] = discard(1, '6p', True)
        sample = self.at_step(self.extract(events), 1, step)[0]
        self.assertTrue(sample['state']['furiten'])
        self.assertEqual(sample['state']['operations'], [8])
        self.assertEqual(sample['action']['action'], 'pass')
        self.assertEqual(sample['labelSource'], 'inferred_pass')
