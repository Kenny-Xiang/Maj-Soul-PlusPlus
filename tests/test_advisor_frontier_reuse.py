"""Precomputed frontier inputs retain special-hand and physical-red semantics."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
import advisor_continuation as continuation
from advisor_continuation import leaf_policy
from advisor_routes import target_policy
from test_advisor import state, tiles


class FrontierReuseTests(unittest.TestCase):
    def test_tile_lookup_fast_path_keeps_validation(self):
        for index, tile in enumerate(advisor.TILES):
            self.assertEqual(advisor.tile_index(tile), index)
        for tile, index in (('0m', 4), ('0p', 13), ('0s', 22), ('１m', 0)):
            self.assertEqual(advisor.tile_index(tile), index)
        for tile in (None, [], {}, 1, '', '1', '10m', '0z', '8z', '1x', 'xm'):
            with self.subTest(tile=tile), self.assertRaises(ValueError):
                advisor.tile_index(tile)

    def test_discard_order_reuses_continuations_without_changing_full_advice(self):
        snapshot = state('147m258p369s12345z')
        snapshot['left'] = 8
        original = deepcopy(snapshot)
        finite = continuation.finite_policy

        def unshared(*args, **kwargs):
            cache = advisor.TABLES.get()
            for key in list(cache):
                if key[0] == 'finite-continuation':
                    del cache[key]
            return finite(*args, **kwargs)

        with patch.object(continuation, 'leaf_policy', wraps=continuation.leaf_policy) as leaf:
            cached = advisor.advise(snapshot)
            shared_calls = leaf.call_count
        with patch.object(advisor, 'finite_policy', side_effect=unshared), patch.object(
                continuation, 'leaf_policy', wraps=continuation.leaf_policy) as leaf:
            reference = advisor.advise(snapshot)
            unshared_calls = leaf.call_count
        self.assertLess(shared_calls, unshared_calls)
        self.assertEqual(cached['status'], 'ready')
        self.assertEqual(reference['status'], 'ready')
        cached.pop('elapsedMs')
        reference.pop('elapsedMs')
        self.assertEqual(cached, reference)
        self.assertEqual(snapshot, original)

    def test_precomputed_shape_preserves_regular_and_seven_pair_outcomes(self):
        for hand, regular_rechecks in (("123m456p78s11z23p4s", 0),
                                       ("11m22p33p44s66s123z", 1)):
            with self.subTest(hand=hand):
                snapshot = state(hand)
                remaining = advisor.unseen_counts(snapshot)
                counts = advisor.counts34(snapshot['hand'])
                sh = advisor.shanten(counts)
                ukeire = sum(t['count'] for t in advisor._improvements(counts, remaining, True))
                args = snapshot['hand'], snapshot, remaining, [], (0, 1, 0)
                expected = leaf_policy(*args)
                with patch.object(advisor, '_ukeire', wraps=advisor._ukeire) as improve:
                    actual = leaf_policy(*args, shape=(counts, sh, ukeire))
                self.assertEqual(actual, expected)
                self.assertEqual(improve.call_count, regular_rechecks)

    def test_shared_red_pool_preserves_available_held_and_visible_reds(self):
        base = state('5p')
        base['melds'][0] = [{'type': 1, 'tiles': tiles(group)}
                            for group in ('222p', '777s', '111s', '888s')]
        target = advisor.counts34(tiles('55p'))
        for location in ('unseen', 'hand', 'river', 'dora', 'meld'):
            with self.subTest(location=location):
                snapshot = deepcopy(base)
                if location == 'hand':
                    snapshot['hand'] = ['0p']
                elif location == 'river':
                    snapshot['rivers'][1] = [{'tile': '0p'}]
                elif location == 'dora':
                    snapshot['doras'] = ['0p']
                elif location == 'meld':
                    snapshot['melds'][1] = [{'type': 0, 'tiles': tiles('406p')}]
                remaining = advisor.unseen_counts(snapshot)
                red_pool = {advisor.tile_index(tile) for tile, _ in advisor._draw_pool(snapshot, remaining)
                            if tile.startswith('0')}
                args = snapshot['hand'], snapshot, remaining, [], (0, 0)
                kwargs = {'targets': [('toitoi', target)], 'average': (0., 0.)}
                expected = target_policy(*args, **kwargs)
                with patch.object(advisor, '_draw_pool', side_effect=AssertionError('pool recomputed')):
                    actual = target_policy(*args, **kwargs, red_pool=red_pool)
                self.assertEqual(actual, expected)
                self.assertIsNotNone(actual[0])


if __name__ == '__main__':
    unittest.main()
