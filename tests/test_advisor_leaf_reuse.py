"""Leaf reuse preserves complete ledgers, physical draws and passed-tile safety."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
import advisor_continuation as continuation
from test_advisor import state, tiles


class LeafReuseTests(unittest.TestCase):
    def test_internal_ukeire_matches_structural_reference_with_changing_stock(self):
        for hand in ("123m456p78s11z23p4s", "11m22p33p44s66s123z", "19m19p19s1234567z"):
            snapshot = state(hand)
            counts = advisor.counts34(snapshot['hand'])
            base = advisor.unseen_counts(snapshot)
            stocks = [base, tuple(max(0, n - 1) for n in base),
                      tuple(n if i % 2 else 0 for i, n in enumerate(base))]
            token = advisor.TABLES.set({})
            try:
                for special in (False, True):
                    for remaining in stocks + stocks[::-1]:
                        current = advisor.shanten(counts, special)
                        expected = []
                        for index, number in enumerate(remaining):
                            trial = list(counts)
                            trial[index] += 1
                            if number and counts[index] < 4 and advisor.shanten(tuple(trial), special) < current:
                                expected.append({'tile': advisor.TILES[index], 'count': number})
                        with self.subTest(hand=hand, special=special, remaining=remaining):
                            self.assertEqual(advisor._ukeire(counts, remaining, special),
                                             sum(t['count'] for t in expected))
                            self.assertEqual(advisor._improvements(counts, remaining, special), expected)
                            changed = advisor._improvements(counts, remaining, special)
                            if changed:
                                changed[0]['count'] = -1
                            self.assertEqual(advisor._improvements(counts, remaining, special), expected)
            finally:
                advisor.TABLES.reset(token)

    def test_leaf_uses_supplied_average_for_regular_and_seven_pair_tails(self):
        for hand in ("123m456p78s11z23p4s", "11m22p33p44s66s123z"):
            snapshot = state(hand)
            snapshot['riichi'][1] = True
            remaining = advisor.unseen_counts(snapshot)
            opponents = advisor._opponents(snapshot, remaining)
            args = snapshot['hand'], snapshot, remaining, opponents, (0, 1, 0)
            expected = continuation.leaf_policy(*args)
            average = advisor._policy_risks((), snapshot, remaining, opponents)[2]
            with self.subTest(hand=hand), patch.object(
                    advisor, '_policy_risks', side_effect=AssertionError('risk inputs recomputed')):
                self.assertEqual(continuation.leaf_policy(*args, average=average), expected)

    def test_full_advice_and_shared_averages_match_each_exact_draw_and_safety(self):
        leaf = continuation.leaf_policy

        def verify_average(hand, snapshot, remaining, opponents, *args, **kwargs):
            expected = advisor._policy_risks((), snapshot, remaining, opponents)[2]
            self.assertEqual(kwargs.pop('average'), expected)
            return leaf(hand, snapshot, remaining, opponents, *args, **kwargs)

        for players, ready, red in ((3, False, 'unseen'), (3, True, 'hand'),
                                     (4, True, 'river'), (4, False, 'meld')):
            snapshot = state('19m258p369s123456z', players)
            snapshot['left'] = 8
            snapshot['riichi'][1] = ready
            snapshot['rivers'][1] = [{'tile': '2p'}, {'tile': '8p'}, {'tile': '1z'}]
            if red == 'hand':
                snapshot['hand'][snapshot['hand'].index('5p')] = '0p'
            elif red == 'river':
                snapshot['rivers'][2] = [{'tile': '0p'}]
            elif red == 'meld':
                snapshot['melds'][2] = [{'type': 0, 'tiles': tiles('406p')}]
            before = deepcopy(snapshot)
            with self.subTest(players=players, ready=ready, red=red):
                with patch.object(advisor, '_policy_risks', wraps=advisor._policy_risks) as risks:
                    actual = advisor.advise(snapshot)
                    shared_calls = risks.call_count
                with patch.object(continuation, 'leaf_policy', side_effect=verify_average) as checked, \
                        patch.object(advisor, '_policy_risks', wraps=advisor._policy_risks) as risks:
                    expected = advisor.advise(snapshot)
                    self.assertGreater(risks.call_count, shared_calls)
                self.assertGreater(checked.call_count, 0)
                self.assertEqual(actual['status'], 'ready')
                self.assertEqual(expected['status'], 'ready')
                actual.pop('elapsedMs')
                expected.pop('elapsedMs')
                self.assertEqual(actual, expected)
                self.assertEqual(snapshot, before)


if __name__ == '__main__':
    unittest.main()
