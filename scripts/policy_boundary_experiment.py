"""Fixed two-arm action-boundary pilot; existing data/cache/App remain read-only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
import torch

from policy_riichi_experiment import identity, selected_rows, sha, write_json
from policy_action_diagnostics import ActionDiagnostics
import policy_corpus_training as corpus
import policy_encoded_cache as cache
from policy_features import ACTIONS, FEATURE_VERSION
from policy_model import PolicyModel
from policy_training import CandidatePolicy, batch_tensors, evaluate, export_model


FOCAL = ('riichi', 'daiminkan')
CONTRACT = {'schemaVersion': 1, 'purpose': 'binary-action-boundary-causal-pilot',
            'trainGames': 4096, 'monitorGames': 512, 'validationGames': 4706,
            'epochs': 2, 'primaryEpoch': 2, 'learningRate': 1e-4,
            'batchSize': 2048, 'gameWindow': 16, 'device': 'mps', 'threads': 2,
            'testSampleReadsAllowed': 0, 'cacheWritesAllowed': 0, 'deploymentAllowed': False}
BASE_WEIGHTS = {'daiminkan': 4, 'chi': 1.5, 'pon': 1.5, 'ankan': 2, 'shouminkan': 2}
CODE_FILES = tuple(ROOT / path for path in (
    'scripts/policy_boundary_experiment.py', 'scripts/policy_riichi_experiment.py',
    'src/policy_corpus_training.py', 'src/policy_training.py', 'src/policy_action_diagnostics.py',
    'src/policy_encoded_cache.py', 'src/policy_features.py', 'src/policy_actions.py',
    'src/policy_model.py', 'src/policy_split.py'))


def check_protected(plan):
    for path, expected in plan['protectedSha256'].items():
        if sha(path) != expected:
            raise ValueError('Protected input changed: ' + path)


def validate_plan(plan):
    if any(plan.get(key) != value for key, value in CONTRACT.items()):
        raise ValueError('Plan differs from the fixed boundary pilot contract')
    expected_arms = {name: {'opportunityWeights': BASE_WEIGHTS,
                            'actionBoundaryWeights': {} if name == 'control' else dict.fromkeys(FOCAL, 1)}
                     for name in ('control', 'boundary')}
    if plan.get('arms') != expected_arms:
        raise ValueError('Only the declared boundary loss may differ between arms')
    required = [str(path) for path in CODE_FILES] + [plan[key] for key in
                ('manifest', 'split', 'cacheIndex', 'parentModel', 'parentResume')]
    if not set(required) <= plan['protectedSha256'].keys():
        raise ValueError('Plan lacks required source/model/cache-index hash bindings')
    if plan['versions'] != {'numpy': np.__version__, 'torch': torch.__version__}:
        raise ValueError('Frozen runtime versions differ')
    if plan['encoderSignature'] != cache.encoder_signature():
        raise ValueError('Frozen encoder differs')
    output = Path(plan['output']).resolve()
    if not output.is_relative_to(ROOT / '.local/improvement'):
        raise ValueError('Output must be inside the isolated research directory')
    readonly = [Path(plan['cache']).resolve()] + [Path(plan[key]).resolve().parent for key in
                ('manifest', 'parentModel', 'parentResume')]
    if any(output.is_relative_to(path) for path in readonly):
        raise ValueError('Output overlaps read-only inputs')
    check_protected(plan)


class ReadOnlyGames:
    def __init__(self, plan, groups):
        self.root = Path(plan['cache'])
        self.allowed = {row['gameId'] for group in groups.values() for row in group}
        self.index, self.loaded = {}, {}
        with Path(plan['cacheIndex']).open() as handle:
            for line in handle:
                record = json.loads(line)
                game = record['gameId']
                if record['players'] == 3 and game in self.allowed:
                    if game in self.index:
                        raise ValueError('Duplicate selected game in cache index')
                    self.index[game] = record
        if self.index.keys() != self.allowed:
            raise ValueError('Cache index lacks a selected game')

    def __call__(self, row):
        game = row['gameId']
        if game not in self.allowed:
            raise ValueError('Sample access outside frozen train/validation selection')
        binding = cache.cache_binding(row, 3)
        record = self.index[game]
        path = cache.cache_path(self.root, binding)
        if record['binding'] != binding or sha(row['path']) != row['sha256']:
            raise ValueError('Sample/cache binding changed')
        digest = sha(path)
        if digest != record['cacheSha256']:
            raise ValueError('Encoded cache changed')
        samples, _ = cache.read_cache(path, binding)
        if len(samples) != row['samples'] or any(s['game'] != game for s in samples):
            raise ValueError('Cached sample count/game differs')
        self.loaded[game] = digest
        return samples


class BinaryNll:
    """Natural focal-vs-complement NLL, retaining the complete negative group."""
    def __init__(self):
        self.items = {action: {label: {'count': 0, 'sum': 0.} for label in
                               ('actualPositive', 'actualNegative')} for action in FOCAL}

    def update(self, sample, logits):
        if len(sample['actions']) < 2:
            return
        types = np.argmax(sample['actions'][:, :len(ACTIONS)], axis=1)
        centered = np.asarray(logits, dtype=np.float64) - float(np.max(logits))
        log_z = float(np.logaddexp.reduce(centered))
        for action in FOCAL:
            focal = types == ACTIONS.index(action)
            if not np.any(focal):
                continue
            positive = bool(focal[sample['target']])
            actual_group = focal if positive else ~focal
            nll = log_z - float(np.logaddexp.reduce(centered[actual_group]))
            item = self.items[action]['actualPositive' if positive else 'actualNegative']
            item['count'] += 1
            item['sum'] += nll

    def report(self):
        return {action: {label: {**item, 'mean': item['sum'] / item['count'] if item['count'] else None}
                         for label, item in strata.items()} for action, strata in self.items.items()}


def denominators(metrics):
    return {**{key: metrics[key] for key in ('samples', 'choices', 'forced')},
            'byAction': {name: item['count'] for name, item in metrics['byAction'].items()},
            'byOpportunity': {name: {key: item[key] for key in
                                    ('opportunityCount', 'actualPositive', 'passAvailable', 'passCorrect')}
                              for name, item in metrics['byOpportunity'].items()}}


def evaluate_group(model, rows, read_game, plan, phase):
    diagnostics, binary, parts = ActionDiagnostics(), BinaryNll(), []
    for start in range(0, len(rows), plan['gameWindow']):
        samples = [s for row in rows[start:start + plan['gameWindow']] for s in read_game(row)]

        class Observer(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.network, self.cursor = model, 0

            def forward(self, *values):
                logits = self.network(*values)
                scores = logits.detach().cpu().numpy()
                tops = logits.argsort(dim=1, descending=True)[:, 0].cpu().tolist()
                for sample, score, top in zip(samples[self.cursor:], scores, tops):
                    legal = score[:len(sample['actions'])]
                    if not np.isfinite(legal).all() or top != int(np.argmax(legal)):
                        raise ValueError('Nonfinite logits or evaluation/runtime tie disagreement')
                    diagnostics.update(sample, legal)
                    binary.update(sample, legal)
                self.cursor += len(scores)
                return logits

        parts.append(evaluate(Observer(), samples, plan['device'], plan['batchSize']))
        if start % 256 == 0:
            print(json.dumps({'phase': phase, 'games': start, 'totalGames': len(rows)}), flush=True)
    metrics, details, binary = corpus.merge_metrics(parts), diagnostics.report(), binary.report()
    for action in FOCAL:
        item = metrics['byOpportunity'].get(action, {})
        for key in ('opportunityCount', 'actualPositive', 'predictedPositive', 'truePositive',
                    'falsePositive', 'falseNegative', 'exactCorrectPositive', 'exactCorrect'):
            if details['byOpportunity'][action][key] != item.get(key, 0):
                raise ValueError('Canonical/diagnostic count mismatch')
        if (binary[action]['actualPositive']['count'] != item.get('actualPositive', 0) or
                sum(value['count'] for value in binary[action].values()) != item.get('opportunityCount', 0)):
            raise ValueError('Binary NLL opportunity denominator mismatch')
    return {'identity': identity(rows), 'metrics': metrics, 'diagnostics': details,
            'binaryNll': binary, 'denominators': denominators(metrics),
            'binaryNllScope': 'Natural focal-vs-all-other-candidates NLL; positive and negative windows reported separately. Confusion uses the highest complete candidate in diagnostics, not a probability threshold.'}


def export_parity(model, path, rows, read_game, device):
    deployed = PolicyModel(path)
    model.eval()
    checked, error = 0, 0.
    for row in rows:
        for sample in read_game(row)[:32 - checked]:
            with torch.no_grad():
                expected = model(*batch_tensors([sample], device)[:4]).cpu().numpy()[0]
            actual = deployed.logits(sample['planes'], sample['globals'], sample['actions'])
            if not np.isfinite(actual).all() or not np.isfinite(expected).all():
                raise ValueError('Nonfinite export logits')
            error = max(error, float(np.max(np.abs(actual - expected))))
            if actual.argmax() != expected.argmax():
                raise ValueError('Export argmax mismatch')
            checked += 1
        if checked == 32:
            break
    if not checked or error > 1e-4:
        raise ValueError('Export numerical parity failed')
    return {'samples': checked, 'maxAbsError': error, 'argmaxAgreement': True}


def compare_reports(control, boundary):
    for name, item in (('control', control), ('boundary', boundary)):
        epochs = [row['epoch'] for row in item['history']]
        if (item['arm'] != name or item['primaryEpoch'] != 2 or len(epochs) > 2
                or epochs != list(range(1, len(epochs) + 1))
                or (item['status'] == 'complete' and epochs != [1, 2])):
            raise ValueError('Arm report violates fixed terminal-epoch policy')
    for key in ('planSha256', 'initialModelSha256', 'parentResumeSha256', 'partitionIdentities'):
        if control[key] != boundary[key]:
            raise ValueError('Arm initialization or data binding differs: ' + key)
    for first, second in zip(control['history'], boundary['history']):
        for key in ('epoch', 'orderSha256', 'trainChoices', 'optimizerSteps', 'trainingSupport'):
            if first[key] != second[key]:
                raise ValueError('Matched training order/support differs: ' + key)
        for group in ('trainMonitor', 'validation'):
            if first[group]['identity'] != second[group]['identity'] or first[group]['denominators'] != second[group]['denominators']:
                raise ValueError('Matched evaluation identity/denominators differ')
    complete = all(item['status'] == 'complete' and [row['epoch'] for row in item['history']] == [1, 2]
                   and item['primaryEpoch'] == 2 for item in (control, boundary))
    result = {'status': 'complete' if complete else 'partial', 'pairedEpochs': min(len(control['history']), len(boundary['history'])),
              'planSha256': control['planSha256'], 'primaryEpoch': 2,
              'scope': 'Matched causal pilot only; no deployment or expanded-corpus acceptance decision.'}
    if complete:
        if control['cacheHashesSha256'] != boundary['cacheHashesSha256']:
            raise ValueError('Matched cache contents differ')
        if any(item['primaryCheckpoint'] != item['history'][-1]['checkpoint'] for item in (control, boundary)):
            raise ValueError('Primary checkpoint must be terminal epoch 2')
        before, after = (item['history'][-1]['validation'] for item in (control, boundary))
        delta = lambda first, second: None if first is None or second is None else second - first
        result['terminalDeltaBoundaryMinusControl'] = {
            **{key: delta(before['metrics'][key], after['metrics'][key]) for key in ('choiceNll', 'choiceTop1')},
            'byOpportunity': {action: {key: delta(before['metrics']['byOpportunity'].get(action, {}).get(key),
                                                   after['metrics']['byOpportunity'].get(action, {}).get(key))
                                      for key in ('precision', 'recall', 'exactPositiveRecall', 'falsePositiveRate', 'exactCandidateTop1')}
                              for action in FOCAL},
            'binaryNll': {action: {label: delta(before['binaryNll'][action][label]['mean'], after['binaryNll'][action][label]['mean'])
                                   for label in ('actualPositive', 'actualNegative')} for action in FOCAL}}
    return result


def run(plan_path, arm):
    plan = json.loads(Path(plan_path).read_text())
    validate_plan(plan)
    if arm not in plan['arms']:
        raise ValueError('Unknown experiment arm')
    torch.set_num_threads(plan['threads'])
    device = plan['device']
    if device == 'mps' and not torch.backends.mps.is_available():
        raise RuntimeError('Frozen experiment requires MPS; no automatic CPU fallback')
    partitions, _, _ = corpus.read_manifest(plan['manifest'], 42, split_file=plan['split'], partitions=('train', 'validation'))
    rows = selected_rows(partitions, plan)
    if any(len(rows[name]) != plan[key] for name, key in
           (('train', 'trainGames'), ('monitor', 'monitorGames'), ('validation', 'validationGames'))):
        raise ValueError('Frozen partition counts differ')
    read_game = ReadOnlyGames(plan, rows)
    exported = PolicyModel(plan['parentModel'])
    model = CandidatePolicy(exported.config).to(device)
    parent = torch.load(plan['parentResume'], map_location='cpu', weights_only=True)
    if parent['epoch'] != 8 or not parent['completed'] or set(parent['model']) != set(exported.weights):
        raise ValueError('Expected completed original epoch-8 parent')
    if any(not torch.equal(parent['model'][key], torch.from_numpy(value)) for key, value in exported.weights.items()):
        raise ValueError('Parent export/resume weights differ')
    model.load_state_dict(parent['model'])
    optimizer = torch.optim.AdamW(model.parameters(), lr=plan['learningRate'], weight_decay=1e-4)
    optimizer.load_state_dict(parent['optimizer'])
    for group in optimizer.param_groups:
        group['lr'] = plan['learningRate']
    rng = np.random.default_rng()
    rng.bit_generator.state = parent['numpyRng']
    torch.set_rng_state(parent['torchRng'])
    output = Path(plan['output'])
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / (arm + '.json')
    if report_path.exists() or list(output.glob(arm + '.epoch-*.npz')):
        raise FileExistsError('Preserve existing arm evidence; use a new output directory')
    started = time.monotonic()
    report = {'status': 'running', 'arm': arm, 'planSha256': sha(plan_path),
              'initialModelSha256': sha(plan['parentModel']), 'parentResumeSha256': sha(plan['parentResume']),
              'partitionIdentities': plan['partitionIdentities'], 'primaryEpoch': plan['primaryEpoch'],
              'initialization': 'Same parent epoch-8 model, AdamW state, NumPy and CPU Torch RNG; only LR reset.',
              'loss': plan['arms'][arm], 'device': device, 'threads': plan['threads'],
              'featureVersion': FEATURE_VERSION, 'history': [],
              'testSampleOrCacheReads': 0, 'cacheWrites': 0, 'appWrites': 0}
    write_json(report_path, report)
    reference_denominators, reference_support = {}, None
    for epoch in range(1, plan['epochs'] + 1):
        model.train()
        order, digest = rng.permutation(len(rows['train'])), hashlib.sha256()
        digest.update(order.astype('<i8').tobytes())
        total, choices, steps, maximum_gradient = 0., 0, 0, 0.
        support = Counter()
        for start in range(0, len(order), plan['gameWindow']):
            samples = [s for index in order[start:start + plan['gameWindow']]
                       for s in read_game(rows['train'][index]) if len(s['actions']) > 1]
            for sample in samples:
                support['recorded:' + sample['action']] += 1
                types = np.argmax(sample['actions'][:, :len(ACTIONS)], axis=1)
                for action in FOCAL:
                    if ACTIONS.index(action) in types:
                        support[action + (':positive' if sample['action'] == action else ':negative')] += 1
            indices = rng.permutation(len(samples))
            digest.update(len(indices).to_bytes(8, 'little'))
            digest.update(indices.astype('<i8').tobytes())
            for offset in range(0, len(indices), plan['batchSize']):
                batch = [samples[index] for index in indices[offset:offset + plan['batchSize']]]
                planes, globals_, actions, mask, targets = batch_tensors(batch, device)
                optimizer.zero_grad(set_to_none=True)
                loss = corpus.supervised_loss(model(planes, globals_, actions, mask), targets, actions, {},
                                              plan['arms'][arm]['opportunityWeights'], plan['arms'][arm]['actionBoundaryWeights'])
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite training loss')
                loss.backward()
                gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
                optimizer.step()
                maximum_gradient = max(maximum_gradient, float(gradient))
                total += float(loss.detach()) * len(batch)
                choices += len(batch)
                steps += 1
            if start % 256 == 0:
                print(json.dumps({'arm': arm, 'epoch': epoch, 'trainGames': start, 'trainChoices': choices}), flush=True)
        if not choices or (reference_support is not None and support != reference_support):
            raise ValueError('Training choice support changed or empty')
        reference_support = support
        checkpoint = output / f'{arm}.epoch-{epoch}.npz'
        export_model(model, checkpoint, {'playerCount': 3, 'purpose': 'behavior-cloning', 'epoch': epoch,
                                        'experimentPlanSha256': report['planSha256'], 'researchOnly': True})
        entry = {'epoch': epoch, 'learningRate': plan['learningRate'], 'trainChoices': choices,
                 'optimizerSteps': steps, 'weightedOnlineTrainLoss': total / choices,
                 'maximumPreclipGradientNorm': maximum_gradient, 'orderSha256': digest.hexdigest(),
                 'trainingSupport': dict(support), 'checkpoint': str(checkpoint), 'checkpointSha256': sha(checkpoint),
                 'exportParity': export_parity(model, checkpoint, rows['monitor'], read_game, device)}
        for name, source in (('trainMonitor', 'monitor'), ('validation', 'validation')):
            entry[name] = evaluate_group(model, rows[source], read_game, plan, f'{arm}-{epoch}-{name}')
            if name in reference_denominators and entry[name]['denominators'] != reference_denominators[name]:
                raise ValueError('Natural evaluation denominators changed across epochs')
            reference_denominators[name] = entry[name]['denominators']
        report['history'].append(entry)
        other_path = output / ('boundary.json' if arm == 'control' else 'control.json')
        if other_path.exists():
            other = json.loads(other_path.read_text())
            compare_reports(report if arm == 'control' else other, report if arm == 'boundary' else other)
        check_protected(plan)
        if sha(plan_path) != report['planSha256']:
            raise ValueError('Frozen plan changed during experiment')
        write_json(report_path, report)
    report.update(status='complete', primaryCheckpoint=report['history'][-1]['checkpoint'],
                  uniqueGamesRead=len(read_game.loaded), elapsedSeconds=time.monotonic() - started,
                  cacheHashesSha256=hashlib.sha256(json.dumps(read_game.loaded, sort_keys=True).encode()).hexdigest())
    write_json(report_path, report)
    if other_path.exists():
        other = json.loads(other_path.read_text())
        paired = compare_reports(report if arm == 'control' else other, report if arm == 'boundary' else other)
        if paired['status'] == 'complete':
            write_json(output / 'comparison.json', paired)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--arm', choices=('control', 'boundary'), required=True)
    args = parser.parse_args()
    run(args.plan, args.arm)


if __name__ == '__main__':
    main()
