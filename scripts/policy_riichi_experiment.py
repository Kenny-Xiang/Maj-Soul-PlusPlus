"""Run a frozen, validation-only riichi opportunity-weight comparison.

Existing corpora, caches, checkpoints and the installed App are read-only.
Each invocation runs one phase; no phase selects or deploys a model.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(rows):
    values = [{key: row[key] for key in ('gameId', 'sha256', 'samples')} for row in rows]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    staged = path.with_suffix(path.suffix + '.tmp')
    staged.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    staged.replace(path)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def selected_rows(partitions, plan):
    result = {'train': partitions['train'][:plan['trainGames']],
              'monitor': partitions['train'][:plan['monitorGames']],
              'validation': partitions['validation']}
    for name, rows in result.items():
        if identity(rows) != plan['partitionIdentities'][name]:
            raise ValueError('Frozen partition identity differs: ' + name)
    if set(row['gameId'] for row in result['train']) & set(row['gameId'] for row in result['validation']):
        raise ValueError('Train and validation overlap')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--phase', choices=('v1', 'parent', 'train'), required=True)
    parser.add_argument('--arm', choices=('control', 'riichi2'))
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if plan['purpose'] != 'riichi-screening-only' or plan['testSampleReadsAllowed'] != 0:
        raise ValueError('Expected a validation-only screening plan')
    if (args.phase == 'train') != (args.arm is not None):
        raise ValueError('Only training phases require an arm')
    for path, expected in plan['protectedSha256'].items():
        if sha(path) != expected:
            raise ValueError('Protected input changed: ' + path)
    source = Path(plan['v1Source']) if args.phase == 'v1' else ROOT / 'src'
    sys.path.insert(0, str(source))
    import numpy as np
    import torch
    import policy_features
    import policy_model
    import policy_encoded_cache as cache
    import policy_training
    # V1 keeps its own feature/model/cache modules; only metric definitions are shared.
    if args.phase == 'v1':
        policy_training = load_module('policy_training', ROOT / 'src/policy_training.py')
    corpus = load_module('experiment_corpus', ROOT / 'src/policy_corpus_training.py')
    sys.path.insert(0, str(ROOT / 'src'))
    from policy_action_diagnostics import ActionDiagnostics
    device = plan['device']
    if device not in ('cpu', 'mps') or plan['threads'] < 1:
        raise ValueError('Invalid frozen execution device')
    torch.set_num_threads(plan['threads'])
    if device == 'mps' and not torch.backends.mps.is_available():
        raise RuntimeError('Frozen experiment requires MPS')
    output = Path(plan['output'])
    output.mkdir(parents=True, exist_ok=True)
    name = args.arm if args.phase == 'train' else args.phase
    report_path = output / (name + '.json')
    if report_path.exists():
        raise FileExistsError('Preserve existing experiment evidence: ' + str(report_path))
    started = time.monotonic()
    partitions, _, _ = corpus.read_manifest(plan['manifest'], 42, split_file=plan['split'])
    rows = selected_rows(partitions, plan)
    allowed = {row['gameId'] for group in rows.values() for row in group}
    del partitions
    cache_root = Path(plan['v1Cache'] if args.phase == 'v1' else plan['v2Cache'])
    bound_hashes = {}
    if args.phase != 'v1':
        with Path(plan['v2CacheIndex']).open() as handle:
            for line in handle:
                record = json.loads(line)
                if record['players'] == 3 and record['gameId'] in allowed:
                    bound_hashes[record['gameId']] = record
        if set(bound_hashes) != allowed:
            raise ValueError('Frozen cache index lacks selected games')
    loaded, loaded_hashes = set(), {}

    def read_game(row):
        if row['gameId'] not in allowed:
            raise ValueError('Sample access outside frozen train/validation allowlist')
        binding = cache.cache_binding(row, 3)
        path = cache.cache_path(cache_root, binding)
        source_hash, cache_hash = sha(row['path']), sha(path)
        if source_hash != row['sha256']:
            raise ValueError('Public source shard changed')
        if bound_hashes:
            record = bound_hashes[row['gameId']]
            if record['binding'] != binding or record['cacheSha256'] != cache_hash:
                raise ValueError('Encoded cache differs from frozen index')
        samples, _ = cache.read_cache(path, binding)
        if len(samples) != row['samples'] or any(s['game'] != row['gameId'] for s in samples):
            raise ValueError('Cache sample count/game mismatch')
        loaded.add(row['gameId'])
        loaded_hashes[row['gameId']] = cache_hash
        return samples

    path = Path(plan['v1Model'] if args.phase == 'v1' else plan['parentModel'])
    exported = policy_model.PolicyModel(path)
    model = policy_training.CandidatePolicy(exported.config)
    model.load_state_dict({key: torch.from_numpy(value.copy()) for key, value in exported.weights.items()})
    model.to(device)
    actions_index = [policy_features.ACTIONS.index(x) for x in ('riichi', 'daiminkan')]

    def evaluate(group, label):
        diagnostic = ActionDiagnostics()
        parts = []
        numeric = {'choiceWindows': 0, 'equalLogitWindows': 0, 'tiedMaximumWindows': 0,
                   'top1TieDisagreements': 0, 'maximumAbsoluteLogit': 0., 'maximumLogitSpan': 0.}
        for start in range(0, len(group), plan['gameWindow']):
            samples = [s for row in group[start:start + plan['gameWindow']] for s in read_game(row)]

            class Observer(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.network = model
                    self.cursor = 0

                def forward(self, *values):
                    logits = self.network(*values)
                    scores = logits.detach().cpu().numpy()
                    batch = samples[self.cursor:self.cursor + len(scores)]
                    canonical_top = logits.argsort(dim=1, descending=True)[:, 0].cpu().tolist()
                    for sample, score, top in zip(batch, scores, canonical_top):
                        legal = score[:len(sample['actions'])]
                        if not np.isfinite(legal).all():
                            raise ValueError('Non-finite legal evaluation logits')
                        if len(legal) > 1:
                            span = float(np.max(legal) - np.min(legal))
                            numeric['choiceWindows'] += 1
                            numeric['equalLogitWindows'] += int(span == 0)
                            numeric['tiedMaximumWindows'] += int(np.sum(legal == np.max(legal)) > 1)
                            numeric['top1TieDisagreements'] += int(top != int(np.argmax(legal)))
                            numeric['maximumAbsoluteLogit'] = max(numeric['maximumAbsoluteLogit'], float(np.max(np.abs(legal))))
                            numeric['maximumLogitSpan'] = max(numeric['maximumLogitSpan'], span)
                        if np.any(sample['actions'][:, actions_index]):
                            diagnostic.update(sample, legal)
                    self.cursor += len(scores)
                    return logits

            parts.append(policy_training.evaluate(Observer(), samples, device, plan['batchSize']))
            if start % (plan['gameWindow'] * 32) == 0:
                print(json.dumps({'phase': label, 'games': start, 'totalGames': len(group)}), flush=True)
        metrics, details = corpus.merge_metrics(parts), diagnostic.report()
        if numeric['top1TieDisagreements']:
            raise ValueError('Metric/runtime tie rules disagree; evidence cannot be accepted')
        for action, values in details['byOpportunity'].items():
            expected = metrics['byOpportunity'].get(action)
            if expected is None:
                continue
            for key in ('opportunityCount', 'actualPositive', 'predictedPositive', 'truePositive',
                        'falsePositive', 'falseNegative', 'exactCorrectPositive', 'exactCorrect'):
                if values[key] != expected[key]:
                    raise ValueError('Diagnostic and canonical metric differ: ' + action + '.' + key)
        return {'validationIdentity': identity(group), 'metrics': metrics, 'diagnostics': details,
                'diagnosticScope': 'Union of riichi-offered and daiminkan-offered windows only',
                'numerics': numeric}

    report = {'status': 'running', 'phase': name, 'planSha256': sha(args.plan),
              'device': device, 'threads': plan['threads'],
              'initialModelSha256': sha(path), 'featureVersion': policy_features.FEATURE_VERSION,
              'validationIdentity': identity(rows['validation']), 'history': [],
              'testSampleOrCacheReads': 0, 'appWrites': 0, 'cacheWrites': 0}
    write_json(report_path, report)
    if args.phase != 'train':
        report['validation'] = evaluate(rows['validation'], name + '-validation')
        report['trainMonitor'] = evaluate(rows['monitor'], name + '-train-monitor')
    else:
        parent = torch.load(plan['parentResume'], map_location='cpu', weights_only=True)
        if parent['epoch'] != 8 or not parent['completed']:
            raise ValueError('Expected completed original epoch-8 parent')
        if any(not torch.equal(parent['model'][key], torch.from_numpy(value))
               for key, value in exported.weights.items()):
            raise ValueError('Resume weights differ from bound exported parent')
        optimizer = torch.optim.AdamW(model.parameters(), lr=plan['learningRate'], weight_decay=1e-4)
        optimizer.load_state_dict(parent['optimizer'])
        for group in optimizer.param_groups:
            group['lr'] = plan['learningRate']
        rng = np.random.default_rng()
        rng.bit_generator.state = parent['numpyRng']
        torch.set_rng_state(parent['torchRng'])
        weights = plan['arms'][args.arm]['opportunityWeights']
        order_digest = hashlib.sha256()
        report['initialization'] = {'modelOptimizerAndRngFromSameParent': True,
                                    'parentResumeSha256': sha(plan['parentResume']),
                                    'opportunityWeights': weights, 'actionWeights': {}}
        weight_audit = {'windows': 0, 'riichiOffered': 0, 'weightChanged': 0,
                        'changedByRecordedType': {}, 'unchangedRiichiAlreadyWeighted': 0}
        for epoch in range(1, plan['epochs'] + 1):
            model.train()
            order = rng.permutation(len(rows['train']))
            order_digest.update(order.tobytes())
            total, choices, steps, max_gradient = 0., 0, 0, 0.
            for start in range(0, len(order), plan['gameWindow']):
                samples = [s for i in order[start:start + plan['gameWindow']]
                           for s in read_game(rows['train'][i]) if len(s['actions']) > 1]
                if epoch == 1:
                    for sample in samples:
                        offered = [policy_features.ACTIONS[i] for i in np.unique(
                            np.argmax(sample['actions'][:, :len(policy_features.ACTIONS)], axis=1))]
                        before = max(plan['arms']['control']['opportunityWeights'].get(a, 1.) for a in offered)
                        after = max(plan['arms']['riichi2']['opportunityWeights'].get(a, 1.) for a in offered)
                        weight_audit['windows'] += 1
                        weight_audit['riichiOffered'] += int('riichi' in offered)
                        if after != before:
                            if 'riichi' not in offered:
                                raise ValueError('Treatment changed a non-riichi window')
                            weight_audit['weightChanged'] += 1
                            name_ = sample['action']
                            weight_audit['changedByRecordedType'][name_] = weight_audit['changedByRecordedType'].get(name_, 0) + 1
                        elif 'riichi' in offered:
                            weight_audit['unchangedRiichiAlreadyWeighted'] += 1
                indices = rng.permutation(len(samples))
                order_digest.update(indices.tobytes())
                for offset in range(0, len(indices), plan['batchSize']):
                    batch = [samples[i] for i in indices[offset:offset + plan['batchSize']]]
                    planes, globals_, actions, mask, targets = policy_training.batch_tensors(batch, device)
                    optimizer.zero_grad(set_to_none=True)
                    loss = corpus.supervised_loss(model(planes, globals_, actions, mask), targets,
                                                  actions, {}, weights)
                    if not torch.isfinite(loss):
                        raise ValueError('Non-finite training loss')
                    loss.backward()
                    gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
                    optimizer.step()
                    max_gradient = max(max_gradient, float(gradient))
                    total += float(loss.detach()) * len(batch)
                    choices += len(batch)
                    steps += 1
                if start % 256 == 0:
                    print(json.dumps({'phase': name, 'epoch': epoch, 'trainGames': start,
                                      'weightedLoss': total / choices}), flush=True)
            checkpoint = output / f'{name}.epoch-{epoch}.npz'
            policy_training.export_model(model, checkpoint, {'playerCount': 3, 'purpose': 'behavior-cloning',
                                          'experimentPlanSha256': sha(args.plan), 'epoch': epoch})
            entry = {'epoch': epoch, 'learningRate': plan['learningRate'], 'trainChoices': choices,
                     'optimizerSteps': steps, 'weightedTrainLoss': total / choices,
                     'maximumPreclipGradientNorm': max_gradient, 'orderSha256': order_digest.hexdigest(),
                     'checkpoint': str(checkpoint), 'checkpointSha256': sha(checkpoint),
                     'trainMonitor': evaluate(rows['monitor'], f'{name}-{epoch}-train-monitor'),
                     'validation': evaluate(rows['validation'], f'{name}-{epoch}-validation')}
            report['history'].append(entry)
            report['opportunityWeightAudit'] = weight_audit
            write_json(report_path, report)
            print(json.dumps({'phase': name, 'epoch': epoch, 'validationNll': entry['validation']['metrics']['choiceNll'],
                              'riichi': entry['validation']['metrics']['byOpportunity']['riichi']}), flush=True)
        # Terminal epoch is fixed before training; do not choose an epoch by its results.
        report['validation'] = report['history'][-1]['validation']
        report['trainMonitor'] = report['history'][-1]['trainMonitor']
        parity_samples = read_game(rows['monitor'][0])[:32]
        deployed = policy_model.PolicyModel(checkpoint)
        max_error = 0.
        for sample in parity_samples:
            tensors = policy_training.batch_tensors([sample], device)
            with torch.no_grad():
                expected = model(*tensors[:4]).cpu().numpy()[0]
            actual = deployed.logits(sample['planes'], sample['globals'], sample['actions'])
            max_error = max(max_error, float(np.max(np.abs(actual - expected))))
            if int(actual.argmax()) != int(expected.argmax()):
                raise ValueError('Export argmax mismatch')
        if max_error > 1e-4:
            raise ValueError('Export numerical parity failed')
        report['exportParity'] = {'samples': len(parity_samples), 'maxAbsError': max_error,
                                  'argmaxAgreement': True}
    for path, expected in plan['protectedSha256'].items():
        if sha(path) != expected:
            raise ValueError('Protected input changed during experiment: ' + path)
    report.update(status='complete', elapsedSeconds=time.monotonic() - started,
                  uniqueGamesRead=len(loaded), cacheHashesSha256=hashlib.sha256(
                      json.dumps(loaded_hashes, sort_keys=True).encode()).hexdigest())
    write_json(report_path, report)
    print(json.dumps({'phase': name, 'status': 'complete', 'seconds': report['elapsedSeconds']}), flush=True)


if __name__ == '__main__':
    main()
