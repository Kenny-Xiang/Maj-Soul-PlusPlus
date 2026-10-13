#!/usr/bin/env python3
"""Read-only paired sample audit of locally archived official and public MJAI games.

Run with the model repository's .venv Python. Writes nothing; JSON goes to stdout.
This compares emitted windows and features, not every legal window or rule.
"""
import argparse
import base64
import collections
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import zstandard

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
import policy_fetch
from policy_actions import action_key, legal_actions
from policy_features import encode_state, GLOBAL_NAMES
from policy_mjai import extract_game


def rows(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def key(sample):
    state = sample['state']
    last, round_ = state['lastAction'], state['round']
    return json.dumps({
        'seat': state['selfSeat'], 'round': [round_[x] for x in ('chang', 'ju', 'ben')],
        'last': [last.get(x) for x in ('name', 'seat', 'tile', 'type')],
        'left': state['left'], 'rivers': [[d['tile'] for d in river] for river in state['rivers']],
        'melds': [[[m['type'], sorted(m['tiles'])] for m in melds] for melds in state['melds']],
    }, sort_keys=True)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--archive', type=Path, required=True)
parser.add_argument('--corpus', type=Path, required=True)
parser.add_argument('--metadata', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
archive, corpus = args.archive.resolve(), args.corpus.resolve()
sources = {r['gameId']: r for r in rows(corpus / 'manifest.jsonl')}
from policy_match_metadata import load_metadata
from policy_convert_mjai import converter_signature
metadata = load_metadata(args.metadata, list(sources.values()))
decoder = policy_fetch.SchemaDecoder(json.loads((archive / 'schema.liqi.json').read_bytes()))
reports = []
for row in rows(archive / 'manifest.jsonl'):
    identifier = row['gameId']
    raw_bytes = (archive / row['files']['response']['path']).read_bytes()
    assert digest(raw_bytes) == row['files']['response']['sha256']
    payload = policy_fetch.load_payload(raw_bytes, row['responseFormat'], decoder)
    payload['data'] = (archive / row['files']['data']['path']).read_bytes()
    normalized = policy_fetch.normalize(payload, decoder, identifier)
    source_records = {}
    round_number, round_step = -1, -1
    for record in normalized['records']:
        if record['name'] == 'RecordNewRound':
            round_number, round_step = round_number + 1, 0
        else:
            round_step += 1
        source_records[(round_number, round_step)] = record
    node = "const fs=require('node:fs'); const {extractGame}=require('./src/policy_replay.cjs'); process.stdout.write(JSON.stringify(extractGame(JSON.parse(fs.readFileSync(0,'utf8')))));"
    result = json.loads(subprocess.run(
        ['node', '-e', node], cwd=ROOT, check=True, capture_output=True,
        input=json.dumps(normalized, default=lambda value: base64.b64encode(value).decode()).encode(),
    ).stdout)
    raw = result['samples']
    source = sources[identifier]
    compressed = (corpus / source['path']).read_bytes()
    assert digest(compressed) == source['compressedSha256']
    decoded = zstandard.ZstdDecompressor().decompress(compressed, max_output_size=33554432)
    events = [json.loads(line) for line in decoded.splitlines()]
    if identifier not in metadata:
        raise ValueError('Pair validation requires verified metadata for every official game')
    mjai, audit = extract_game(events, identifier, match_metadata=metadata[identifier])
    rawmap = collections.defaultdict(list)
    for sample in raw:
        rawmap[key(sample)].append(sample)
    report = dict(gameId=identifier, rawSamples=len(raw), mjaiSamples=len(mjai), matched=0,
                  noMatch=0, ambiguous=0, maskEqual=0, labelEqual=0, planeEqual=0,
                  globalMismatchCounts=collections.Counter(), mismatches=[],
                  officialExtractionAudit=result['audit'], mjaiExtractionAudit=audit)
    matched_raw_ids = collections.Counter()
    for sample in mjai:
        candidates = rawmap[key(sample)]
        if not candidates:
            report['noMatch'] += 1
            continue
        if len(candidates) != 1:
            report['ambiguous'] += 1
            continue
        original = candidates[0]
        matched_raw_ids[original['decisionId']] += 1
        report['matched'] += 1
        mj_keys = {action_key(a) for a in legal_actions(sample['state'])}
        raw_keys = {action_key(a) for a in legal_actions(original['state'])}
        report['maskEqual'] += mj_keys == raw_keys
        report['labelEqual'] += action_key(sample['action']) == action_key(original['action'])
        mj_planes, mj_globals = encode_state(sample['state'])
        raw_planes, raw_globals = encode_state(original['state'])
        report['planeEqual'] += bool(np.array_equal(mj_planes, raw_planes))
        differing_globals = {GLOBAL_NAMES[i]: [float(raw_globals[i]), float(mj_globals[i])]
                             for i in np.where(mj_globals != raw_globals)[0]}
        report['globalMismatchCounts'].update(differing_globals.keys())
        if (mj_keys != raw_keys or differing_globals or not np.array_equal(mj_planes, raw_planes)
                or action_key(sample['action']) != action_key(original['action'])):
            parts = original['decisionId'].split(':')
            source_record = source_records[(int(parts[1]), int(parts[-2]))]
            report['mismatches'].append(dict(
                rawDecisionId=original['decisionId'], mjaiDecisionId=sample['decisionId'],
                action=sample['action'], rawOnly=sorted(raw_keys-mj_keys), mjaiOnly=sorted(mj_keys-raw_keys),
                unexpectedGlobals=differing_globals,
                rawOperations=original['state']['operationDetails'],
                mjaiOperations=sample['state']['operationDetails'],
                originalRecordName=source_record['name'],
                originalRecordFields={k: v for k, v in source_record['data'].items()
                                      if k in ('seat', 'tile', 'zhenting', 'operations', 'operation')},
            ))
    report['reusedRawWindows'] = sum(n - 1 for n in matched_raw_ids.values() if n > 1)
    reports.append(report)

totals = {name: sum(r[name] for r in reports) for name in
          ('rawSamples', 'mjaiSamples', 'matched', 'noMatch', 'ambiguous', 'maskEqual', 'labelEqual', 'planeEqual', 'reusedRawWindows')}
global_counts = collections.Counter()
for report in reports:
    global_counts.update(report['globalMismatchCounts'])
passed = (totals['matched'] > 0 and totals['matched'] == totals['maskEqual'] == totals['labelEqual'] == totals['planeEqual']
          and totals['noMatch'] == totals['ambiguous'] == totals['reusedRawWindows'] == 0 and not global_counts)
report = dict(
    passed=passed, converterSignature=converter_signature(),
    officialReplaySignature=digest((ROOT/'src/policy_replay.cjs').read_bytes()),
    metadataSha256=digest(args.metadata.read_bytes()),
    scope='Offline paired audit of 19 archived official replays and same-UUID public MJAI. Fresh official extractor and MJAI converter. Matching emitted windows only; missing or excluded windows are not correctness claims. No training or network requests.',
    matchingKey='seat + chang/ju/ben + last event name/seat/tile/type + wall remaining + ordered river tiles + sorted meld tiles/types; no labels, operation lists, scores, hands, or furiten in key',
    limitations=['All games are from the same early chronological slice, not a random corpus sample.',
                 'Source event correctness, operation-mask semantics and feature equivalence are separate checks.',
                 'Matched masks compare existing official adapter candidates with reconstructed MJAI candidates, not raw wire lists directly.',
                 'Original records can omit operation lists; MJAI excludes kan suffixes and censored responses.'],
    games=len(reports), totals=totals, globalMismatchCounts=global_counts, reports=reports,
)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ('passed', 'games', 'totals', 'globalMismatchCounts', 'converterSignature')}, indent=2))
raise SystemExit(0 if passed else 2)
