"""Synthetic checks for paired initialization, read-only data and fixed epochs."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
    import torch
    import zstandard
except ImportError:
    torch = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
if torch is not None:
    import policy_boundary_experiment as runner


@unittest.skipIf(torch is None, 'optional policy training dependencies are not installed')
class BoundaryExperimentTests(unittest.TestCase):
    def sample(self, game, names, target):
        from policy_features import PLANE_NAMES, GLOBAL_NAMES, ACTION_NAMES
        actions = np.zeros((len(names), len(ACTION_NAMES)), dtype=np.float32)
        for index, name in enumerate(names):
            actions[index, runner.ACTIONS.index(name)] = 1
        return {'game': game, 'planes': np.zeros((len(PLANE_NAMES), 34), dtype=np.float32),
                'globals': np.zeros(len(GLOBAL_NAMES), dtype=np.float32), 'actions': actions,
                'target': target, 'action': names[target], 'labelSource': 'accepted'}

    def test_binary_negative_sums_every_other_type_and_keeps_zero_support_explicit(self):
        diagnostic = runner.BinaryNll()
        negative = self.sample('a', ['daiminkan', 'pon', 'pass'], 2)
        positive = self.sample('b', ['daiminkan', 'daiminkan', 'pass'], 1)
        diagnostic.update(negative, np.log([.2, .3, .5]))
        diagnostic.update(positive, np.log([.2, .3, .5]))
        diagnostic.update(self.sample('forced', ['riichi'], 0), np.zeros(1))
        report = diagnostic.report()
        self.assertAlmostEqual(report['daiminkan']['actualNegative']['mean'], -np.log(.8))
        self.assertAlmostEqual(report['daiminkan']['actualPositive']['mean'], -np.log(.5))
        self.assertIsNone(report['riichi']['actualPositive']['mean'])
        self.assertEqual(report['riichi']['actualPositive']['count'], 0)
        diagnostic.update(negative, np.array([10000., -10000., -9999.]))
        self.assertTrue(np.isfinite(diagnostic.report()['daiminkan']['actualNegative']['mean']))

    def fixture(self, root):
        from policy_split import freeze_split
        source, models, cache_root = root / 'source', root / 'models', root / 'cache'
        source.mkdir()
        models.mkdir()
        rows, sources = [], []
        for index in range(6):
            game = f'game-{index}'
            digest = hashlib.sha256(game.encode()).hexdigest()
            rows.append({'gameId': game, 'path': game + '.sample', 'sha256': digest, 'samples': 5,
                         'sourceSha256': hashlib.sha256(('source:' + game).encode()).hexdigest(),
                         'converterSignature': 'a' * 64})
            sources.append({'gameId': game, 'compressedSha256': rows[-1]['sourceSha256'],
                            'eventsSha256': hashlib.sha256(('events:' + game).encode()).hexdigest()})
        split = freeze_split(sources, [row['gameId'] for row in rows], {}, count=6)
        manifest, split_path = source / 'manifest.jsonl', source / 'split.json'
        manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        split_path.write_text(json.dumps(split))
        partitions, _, _ = runner.corpus.read_manifest(manifest, 42, split_file=split_path,
                                                        partitions=('train', 'validation'))
        index_rows = []
        for group in partitions.values():
            for row in group:
                game = row['gameId']
                row['path'].write_text(game)
                samples = [self.sample(game, ['discard', 'riichi'], target) for target in (0, 1)]
                samples += [self.sample(game, ['daiminkan', 'pon', 'pass'], target) for target in (0, 2)]
                samples.append(self.sample(game, ['discard'], 0))
                binding = runner.cache.cache_binding(row, 3)
                path = runner.cache.cache_path(cache_root, binding)
                runner.cache.write_cache(path, binding, samples, {})
                index_rows.append({'gameId': game, 'players': 3, 'binding': binding,
                                   'cacheSha256': runner.sha(path)})
        index_path = source / 'index.jsonl'
        index_path.write_text(''.join(json.dumps(row) + '\n' for row in index_rows))
        torch.set_num_threads(1)
        torch.manual_seed(23)
        model = runner.CandidatePolicy({'channels': 4, 'blocks': 1, 'hidden': 8})
        optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=1e-4)
        tensors = runner.batch_tensors(samples[:4], 'cpu')
        runner.corpus.supervised_loss(model(*tensors[:4]), tensors[4], tensors[2], {}).backward()
        optimizer.step()
        parent_model, resume = models / 'parent.npz', models / 'resume.pt'
        runner.export_model(model, parent_model, {'playerCount': 3, 'purpose': 'behavior-cloning'})
        torch.save({'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                    'numpyRng': np.random.default_rng(17).bit_generator.state,
                    'torchRng': torch.get_rng_state(), 'epoch': 8, 'completed': True}, resume)
        contract = {**runner.CONTRACT, 'trainGames': 4, 'monitorGames': 2, 'validationGames': 1,
                    'device': 'cpu', 'threads': 1, 'batchSize': 4, 'gameWindow': 2}
        paths = {'manifest': str(manifest), 'split': str(split_path), 'cacheIndex': str(index_path),
                 'parentModel': str(parent_model), 'parentResume': str(resume)}
        plan = {**contract, **paths, 'cache': str(cache_root),
                'output': str(root / '.local/improvement/pilot'),
                'versions': {'numpy': np.__version__, 'torch': torch.__version__},
                'encoderSignature': runner.cache.encoder_signature(),
                'arms': {name: {'opportunityWeights': runner.BASE_WEIGHTS,
                                'actionBoundaryWeights': {} if name == 'control' else dict.fromkeys(runner.FOCAL, 1)}
                         for name in ('control', 'boundary')},
                'partitionIdentities': {'train': runner.identity(partitions['train']),
                                        'monitor': runner.identity(partitions['train'][:2]),
                                        'validation': runner.identity(partitions['validation'])},
                'protectedSha256': {str(path): runner.sha(path) for path in
                                     [*runner.CODE_FILES, *paths.values()]}}
        plan_path = root / 'plan.json'
        plan_path.write_text(json.dumps(plan))
        return plan_path, plan, contract, split

    def test_two_arm_cpu_fixture_preserves_inputs_matches_order_and_reports_terminal_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan_path, plan, contract, split = self.fixture(root)
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'CONTRACT', contract), \
                    patch.object(runner.cache, 'write_cache', side_effect=AssertionError('cache write')), \
                    patch.object(runner.corpus, 'load_game', side_effect=AssertionError('mutable loader')), \
                    redirect_stdout(io.StringIO()):
                control = runner.run(plan_path, 'control')
                boundary = runner.run(plan_path, 'boundary')
                with self.assertRaises(FileExistsError):
                    runner.run(plan_path, 'control')
                runner.check_protected(plan)
                bad = deepcopy(plan)
                del bad['protectedSha256'][str(runner.CODE_FILES[0])]
                with self.assertRaisesRegex(ValueError, 'lacks required'):
                    runner.validate_plan(bad)
                bad = deepcopy(plan)
                bad['protectedSha256'][plan['manifest']] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'Protected input changed'):
                    runner.validate_plan(bad)
                bad = deepcopy(plan)
                bad['arms']['boundary']['opportunityWeights']['riichi'] = 2
                with self.assertRaisesRegex(ValueError, 'Only the declared boundary'):
                    runner.validate_plan(bad)
            comparison = json.loads((Path(plan['output']) / 'comparison.json').read_text())
            self.assertEqual(comparison['status'], 'complete')
            self.assertEqual(comparison['primaryEpoch'], 2)
            for report in (control, boundary):
                self.assertEqual([row['epoch'] for row in report['history']], [1, 2])
                self.assertEqual(report['primaryCheckpoint'], report['history'][1]['checkpoint'])
                self.assertNotIn('bestEpoch', report)
                self.assertEqual(report['uniqueGamesRead'], 5)
                self.assertEqual(report['testSampleOrCacheReads'], 0)
                for epoch in report['history']:
                    self.assertTrue(epoch['exportParity']['argmaxAgreement'])
                    self.assertEqual(epoch['trainChoices'], 16)
                    self.assertEqual(epoch['validation']['binaryNll']['riichi']['actualNegative']['count'], 1)
                    self.assertEqual(epoch['validation']['denominators']['forced'], 1)
            for field, value in (('orderSha256', 'changed'), ('trainChoices', 1), ('trainingSupport', {})):
                bad = deepcopy(boundary)
                bad['history'][1][field] = value
                with self.assertRaisesRegex(ValueError, 'training order/support'):
                    runner.compare_reports(control, bad)
            bad = deepcopy(boundary)
            bad['history'][1]['validation']['denominators']['choices'] += 1
            with self.assertRaisesRegex(ValueError, 'denominators'):
                runner.compare_reports(control, bad)
            bad = deepcopy(boundary)
            bad['history'] = bad['history'][:1]
            with self.assertRaisesRegex(ValueError, 'terminal-epoch'):
                runner.compare_reports(control, bad)
            bad = deepcopy(boundary)
            bad['primaryCheckpoint'] = bad['history'][0]['checkpoint']
            with self.assertRaisesRegex(ValueError, 'terminal epoch 2'):
                runner.compare_reports(control, bad)
            groups = {'train': [{'gameId': row} for row in split['groups']['train']],
                      'validation': [{'gameId': row} for row in split['groups']['validation']]}
            reader = runner.ReadOnlyGames(plan, groups)
            with self.assertRaisesRegex(ValueError, 'outside frozen'):
                reader({'gameId': split['groups']['test'][0]})


if __name__ == '__main__':
    unittest.main()
