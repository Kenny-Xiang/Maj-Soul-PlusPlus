"""The bounded pilot must not change the frozen train/validation membership."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    'riichi_experiment', Path(__file__).resolve().parents[1] / 'scripts/policy_riichi_experiment.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class PartitionTests(unittest.TestCase):
    def setUp(self):
        def row(name):
            return {'gameId': name, 'sha256': name * 64, 'samples': 10, 'path': Path(name)}
        self.partitions = {'train': [row('a'), row('b'), row('c')],
                           'validation': [row('d')], 'test': [row('e')]}
        self.plan = {'trainGames': 2, 'monitorGames': 1, 'partitionIdentities': {
            'train': runner.identity(self.partitions['train'][:2]),
            'monitor': runner.identity(self.partitions['train'][:1]),
            'validation': runner.identity(self.partitions['validation'])}}

    def test_only_frozen_training_prefix_and_all_validation_are_allowed(self):
        selected = runner.selected_rows(self.partitions, self.plan)
        self.assertEqual(set(selected), {'train', 'monitor', 'validation'})
        self.assertEqual([r['gameId'] for r in selected['train']], ['a', 'b'])
        self.assertEqual(selected['validation'], self.partitions['validation'])

    def test_reordering_or_changing_source_cannot_silently_change_experiment(self):
        self.partitions['train'].reverse()
        with self.assertRaisesRegex(ValueError, 'identity'):
            runner.selected_rows(self.partitions, self.plan)

    def test_overlap_is_rejected_even_if_identity_is_recomputed(self):
        self.partitions['validation'] = self.partitions['train'][:1]
        self.plan['partitionIdentities']['validation'] = runner.identity(self.partitions['validation'])
        with self.assertRaisesRegex(ValueError, 'overlap'):
            runner.selected_rows(self.partitions, self.plan)


if __name__ == '__main__':
    unittest.main()
