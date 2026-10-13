"""Mahjong Soul own-turn decision semantics over reconstructed MJAI masks."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from test_policy_mjai_review import WAITING, discard, draw, finish, opening, riichienv


def riichi_draw_prefix(tile, hand=WAITING):
    events = opening([hand, [], [], []], ['C', 'P', 'F', 'S', tile])
    events += [draw(0, 'C'), {'type': 'reach', 'actor': 0}, discard(0, 'C', True),
               {'type': 'reach_accepted', 'actor': 0}]
    for seat, drawn in ((1, 'P'), (2, 'F'), (3, 'S')):
        events += [draw(seat, drawn), discard(seat, drawn, True)]
    return events + [draw(0, tile)]


@unittest.skipIf(riichienv is None, 'install requirements-conversion.txt for MJAI checks')
class MjaiCandidateTests(unittest.TestCase):
    def extract(self, events):
        from policy_mjai import extract_game
        return extract_game(events, 'synthetic-candidates')

    def candidates(self, sample):
        from policy_actions import legal_actions
        return legal_actions(sample['state'])

    def at_step(self, samples, step):
        return [s for s in samples if s['seat'] == 0 and s['state']['lastStep'] == step]

    def test_riichi_forced_tsumogiri_has_no_decision(self):
        events = riichi_draw_prefix('W')
        samples, audit = self.extract(finish(events + [discard(0, 'W', True)]))
        self.assertFalse(self.at_step(samples, len(events) - 1))
        self.assertTrue(any(s['action']['action'] == 'riichi' for s in samples))
        self.assertEqual(audit['excluded'].get('label_not_in_reconstructed_mask', 0), 0)

    def test_riichi_tsumo_and_cancel_share_the_same_frozen_mask(self):
        events = riichi_draw_prefix('6p')
        win, _ = self.extract(events + [{'type': 'hora', 'actor': 0, 'target': 0},
                                       {'type': 'end_kyoku'}, {'type': 'end_game'}])
        declined, audit = self.extract(finish(events + [discard(0, '6p', True)]))
        winner = self.at_step(win, len(events) - 1)[0]
        passed = self.at_step(declined, len(events) - 1)[0]
        self.assertEqual(winner['state'], passed['state'])
        self.assertEqual({a['action'] for a in self.candidates(winner)}, {'tsumo', 'pass'})
        self.assertFalse(winner['state']['canDiscard'])
        self.assertEqual(winner['action']['action'], 'tsumo')
        self.assertEqual(passed['action'], {'action': 'pass', 'consumed': []})
        self.assertEqual(passed['labelSource'], 'inferred_pass')
        self.assertEqual(audit['excluded'].get('label_not_in_reconstructed_mask', 0), 0)

    def test_riichi_red_ankan_or_pass_preserves_physical_consumption(self):
        hand = ['5p'] * 3 + ['1m', '2m', '3m', '4s', '5s', '6s', '7s', '8s', '9s', 'E']
        events = riichi_draw_prefix('5pr', hand)
        quad = {'type': 'ankan', 'actor': 0, 'consumed': ['5p', '5p', '5p', '5pr']}
        accepted, _ = self.extract(finish(events + [quad]))
        declined, _ = self.extract(finish(events + [discard(0, '5pr', True)]))
        kan = self.at_step(accepted, len(events) - 1)[0]
        passed = self.at_step(declined, len(events) - 1)[0]
        self.assertEqual(kan['state'], passed['state'])
        self.assertEqual({a['action'] for a in self.candidates(kan)}, {'ankan', 'pass'})
        self.assertEqual(sorted(kan['action']['consumed']), ['0p', '5p', '5p', '5p'])
        self.assertEqual(passed['action']['action'], 'pass')
        self.assertEqual(passed['labelSource'], 'inferred_pass')

    def test_unlocked_win_keeps_discard_candidates_and_exact_moqie(self):
        events = opening([WAITING, [], [], []], ['C', 'P', 'F', 'S', '6p'])
        events += [draw(0, 'C'), discard(0, 'C', True)]
        for seat, tile in ((1, 'P'), (2, 'F'), (3, 'S')):
            events += [draw(seat, tile), discard(seat, tile, True)]
        events += [draw(0, '6p')]
        samples, _ = self.extract(finish(events + [discard(0, '6p', True)]))
        sample = self.at_step(samples, len(events) - 1)[0]
        self.assertIn('tsumo', {a['action'] for a in self.candidates(sample)})
        self.assertNotIn('pass', {a['action'] for a in self.candidates(sample)})
        self.assertTrue(sample['state']['canDiscard'])
        self.assertEqual(sample['action'], {'action': 'discard', 'tile': '6p', 'consumed': [], 'moqie': True})

    def test_non_tsumogiri_does_not_fabricate_a_cancel_label(self):
        events = riichi_draw_prefix('6p')
        invalid = deepcopy(events) + [discard(0, '6p', False)]
        samples, audit = self.extract(finish(invalid))
        self.assertFalse(self.at_step(samples, len(events) - 1))
        self.assertEqual(audit['excluded']['label_not_in_reconstructed_mask'], 1)

    def test_known_east_metadata_selects_east_engine_and_unknown_is_explicit(self):
        from policy_mjai import extract_game, RiichiEnv
        identifier = '260101-11111111-2222-4333-8444-555555555555'
        metadata = {'schemaVersion': 1, 'gameId': identifier, 'modeId': 15,
                    'playerCount': 4, 'roundCount': 1, 'sourceCompressedSha256': '1' * 64,
                    'provenance': {'kind': 'official-header-config', 'archive': 'fixture',
                                   'headSha256': '2' * 64, 'responseSha256': '3' * 64,
                                   'schemaSha256': '4' * 64}}
        events = finish(riichi_draw_prefix('W') + [discard(0, 'W', True)])
        with patch('policy_mjai.RiichiEnv', wraps=RiichiEnv) as engine:
            samples, audit = extract_game(events, identifier, match_metadata=metadata)
        self.assertEqual(engine.call_args.kwargs['game_mode'], '4p-red-east')
        self.assertTrue(all(s['state']['match']['roundCount'] == 1 for s in samples))
        self.assertEqual(audit['ruleEngineGameMode'], '4p-red-east')
        self.assertFalse(audit['ruleEngineMatchLengthAssumed'])
        unknown, audit = extract_game(events, identifier)
        self.assertTrue(all(s['state']['match']['roundCount'] is None for s in unknown))
        self.assertEqual(audit['ruleEngineGameMode'], '4p-red-half')
        self.assertTrue(audit['ruleEngineMatchLengthAssumed'])
