# Policy replay import and public data provenance

`scripts/policy_fetch.py` imports Mahjong Soul `fetchGameRecord` exports into
the replay extractor's input format. It uses Python's standard library only.
It neither logs in nor reads browser sessions, cookies, account credentials,
or private game logs. This importer does not obtain replays from a share link
or enumerate players' histories.

## Reproduce the public four-player smoke input

```sh
python3 scripts/policy_fetch.py \
  --public-sample four-player-210815 \
  --output .local/policy-data/public-four-player.normalized.json
```

This downloads one complete, publicly shared **Mahjong Soul** replay export,
checks its exact byte count and SHA-256, saves the original under
`.local/policy-data/four-player-210815.source.json`, and writes the normalized
stream. `.local/` is ignored by Git; no external whole-game replay is committed.

| Field | Pinned value |
| --- | --- |
| Provider | `Fat-pig-Cui/misc-code` |
| Commit | `198741f373edbf5dabe4dc6c7ce66305d5be43a6` |
| File | `paipu/paipu_210815-6da08e40-2605-42fb-a5e3-f8aa5940362a.json` |
| Bytes | `765156` |
| SHA-256 | `dfee868402e7f875a8eb21b39fbb5df6753ae2803362f84f0aa518c6b16d47a3` |
| Game UUID | `210815-6da08e40-2605-42fb-a5e3-f8aa5940362a` |
| Format | `ResGameRecord` JSON with decoded `GameDetailRecords.actions`, version `210715` |
| Mode | Four players, ranked South game; `head.config.meta.mode_id = 12` |

[Pinned source file](https://github.com/Fat-pig-Cui/misc-code/blob/198741f373edbf5dabe4dc6c7ce66305d5be43a6/paipu/paipu_210815-6da08e40-2605-42fb-a5e3-f8aa5940362a.json),
[export script](https://github.com/Fat-pig-Cui/misc-code/blob/198741f373edbf5dabe4dc6c7ce66305d5be43a6/paipu/GetPaipuJSON.js),
[provider's explanation](https://github.com/Fat-pig-Cui/misc-code/blob/198741f373edbf5dabe4dc6c7ce66305d5be43a6/doc/%E7%89%8C%E8%B0%B1%E9%87%8C%E9%9D%A2%E5%88%B0%E5%BA%95%E8%AE%B0%E8%BD%BD%E4%BA%86%E4%BB%80%E4%B9%88/README.md).
The provider's repository has an [MIT license, copyright 2024 Chubbypig](https://github.com/Fat-pig-Cui/misc-code/blob/198741f373edbf5dabe4dc6c7ce66305d5be43a6/LICENSE).
This is a third-party export of the official replay format, not a dataset
published or licensed by Mahjong Soul itself. The importer was written for
this project; it does not copy the provider's export implementation.

Import verification on 2026-10-10 found 828 result records, 534 subsequent
user inputs, and four pre-game inputs. The results include 9 rounds,
408 discards, 379 draws, 23 calls, 8 wins, and 1 exhaustive draw. The file
has a final `head.result` for all four seats and ends in `RecordHule`.
These counts verify parsing, not strength, prediction accuracy, or data
representativeness. One game cannot supply independent train/validation/test
sets. All of its seats and decisions must stay in the same split.

An independent cached-source → importer → replay extractor → legal-candidate
check emitted 486 labeled decisions from 489 windows: 484 labels matched
explicit user inputs and 2 used the resulting action. All 486 labels matched
exactly one candidate. Three response windows were censored; 17 actor turns
had no recorded operations and were excluded rather than assigned invented
legal masks. The resulting classes were 384 discards, 64 passes, 15 pons,
7 riichi declarations, 5 rons, 8 chis, and 3 tsumos. This particular game does
not validate kans, nine-terminals aborts, or kita.

No complete public three-player Mahjong Soul source was verified during this
implementation. Three-player replay cases in the committed tests are
synthetic and must not be reported as real-log validation. Akagi's current
native bot training examples use Tenhou logs; they are not substitutes for
official-format Mahjong Soul samples. An inspected external serialized
fixture with `head.uuid = "sample"` was also excluded from the real-data smoke.

## Import local decoded JSON

```sh
python3 scripts/policy_fetch.py --input /path/to/export.json \
  --output .local/policy-data/my-game.normalized.json
```

Accepted JSON structures are:

- `ResGameRecord` with `head` and `data: {name: ".lq.GameDetailRecords", data: ...}`.
- `ResGameRecord` with `data` containing base64 or an array of protobuf bytes;
  this requires the pinned schema below.
- Decoded `GameDetailRecords` using `records` or `actions` (version `210715`).
- `{gameId, head, records: [{name: "Record...", data: {...}, userInputs: [...]}]}`.
- A list of decoded record wrappers, with an explicit `--game-id`.

Provide `--game-id UUID` when no `head.uuid`/`gameId` exists. This identifier is
mandatory so a downstream splitter can keep all perspectives of one match
together. An explicit ID cannot override a conflicting existing UUID. A
headless binary or record array can use `--head-json /path/to/head.json` to
attach its original `RecordGame` header (including rules/mode); the sidecar's
hash is recorded. A headless import alone is not sufficient for the replay
extractor's standard-ranked-rules gate. `--url https://...` accepts an explicitly supplied public JSON or
binary URL. Downloads are limited to 16 MiB and redirects are refused.

## Decode protobuf using the pinned official client schema

The schema is an official public client resource, downloaded separately into
the ignored cache, rather than vendored in this repository:

| Field | Pinned value |
| --- | --- |
| URL | [liqi.json 0.11.243.w](https://game.maj-soul.com/1/v0.11.243.w/res/proto/liqi.json) |
| Bytes | `286815` |
| SHA-256 | `f2955c3d10cf2d42bee9309f672c062540941ea0cffe1bd62e3f436c7afc404c` |

```sh
# Raw Wrapper(name=".lq.GameDetailRecords", data=...)
python3 scripts/policy_fetch.py --input /path/to/game.bin \
  --format wrapper --fetch-schema --game-id UUID \
  --head-json /path/to/original-record-head.json \
  --output .local/policy-data/my-game.normalized.json

# Reuse the cached, hash-checked schema without any network request.
python3 scripts/policy_fetch.py --input /path/to/response.bin \
  --format response --schema .local/policy-data/liqi-0.11.243.w.json \
  --output .local/policy-data/my-game.normalized.json
```

`--format response` means raw `ResGameRecord` protobuf; `ws-response` means
the response frame byte `03`, a two-byte request ID, and the outer `Wrapper`;
`detail` means bare `GameDetailRecords`. `auto` recognizes JSON and otherwise
assumes a raw game-detail Wrapper. Base64 within JSON is supported; base64
text files should be decoded to bytes before using a binary format option.
The importer does not guess which response method a captured frame belongs to:
only pass a known `fetchGameRecord` response.

A `data_url` embedded in an export is never fetched automatically. If the
response only contains a URL, inspect it and explicitly repeat the same URL:

```sh
python3 scripts/policy_fetch.py --input /path/to/response.json \
  --data-url 'https://the-exact-host/path-from-that-response' \
  --fetch-schema --output .local/policy-data/my-game.normalized.json
```

Binary fields omitted on the wire remain absent. A zero-valued scalar must
be interpreted according to its protobuf definition by the replay layer;
the importer does not fabricate an empty `operations` list when none was
recorded. Unknown field numbers are recorded in `source.unknownFields` for
schema auditing. A schema with a different hash is rejected rather than
silently substituted.

## Normalized contract and verification boundaries

Each `records[i].userInputs` contains the requests **after** that result and
**before** the next result, in source order. Result-less actions are retained.
Requests before the first result are kept in `initialUserInputs`. Original
request fields are preserved, with `_actionIndex`/`_passed` metadata added;
the metadata is for auditing and must not become policy features. A result
has `sourceActionIndex` when it came from an action stream. `head` and the
all-seat record data remain privileged replay inputs: the separate projection
layer must remove opponents' hidden information and future outcomes before
creating model observations.

Output `source` records input byte count/hash, explicit source URL or local
path, and the schema hash for binary decoding. Unit tests use synthetic
protobuf and JSON fixtures, covering old record arrays, result-less requests,
packed signed integers, absent-field presence, raw response frames, malformed
bytes, schema mismatch, and refusal to follow embedded URLs. The complete
public game verifies the decoded-JSON path; a genuine complete raw binary
game and a genuine complete three-player game remain separate validation
requirements.

```sh
python3 -m unittest discover -s tests -p test_policy_fetch.py -v
python3 -m unittest discover -s tests -p test_policy_decoder_review.py -v
```

The independent whole-game review test skips when the pinned public source
has not been downloaded; it never performs a network request during testing.
