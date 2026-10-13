# Policy replay import and public data provenance

For bulk MJAI conversions, see the [corpus provenance below](#public-mahjong-soul-throne-mjai-corpus)
and the [conversion and streaming-training guide](policy-mjai.md).

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
public game verifies the decoded-JSON path. The authenticated three-game
verification below also covers complete raw binary four-player games.
A genuine complete three-player game remains a separate validation requirement.

```sh
python3 -m unittest discover -s tests -p test_policy_fetch.py -v
python3 -m unittest discover -s tests -p test_policy_decoder_review.py -v
```

The independent whole-game review test skips when the pinned public source
has not been downloaded; it never performs a network request during testing.

## Public Mahjong Soul Throne MJAI corpus

The user accepted MJAI conversions of official Mahjong Soul games. We acquired
the Mahjong Soul Throne shards from the public
[nikketryhard/tenhou-houou-mjai dataset](https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai),
pinned to revision `6450bb584cef43ede3b514df48e301a832c6818b`. The selected
corpus uses `majsoul-throne-2026.tar`; Tenhou shards are not included. The
[publisher's scraper documentation](https://github.com/NikkeTryHard/tenhou-to-mjai/blob/main/docs/majsoul-scraper.md)
describes the Mahjong Soul source pipeline.

| Archive | Bytes | SHA256 |
| --- | --- | --- |
| [majsoul-throne-2026.tar](https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai/resolve/6450bb584cef43ede3b514df48e301a832c6818b/majsoul-throne-2026.tar) | 170055680 | `86319ea7d42ff9ec6d877567ad83d1788c5840a49abaf672e6330d6132501f02` |
| [majsoul-throne-2019.tar](https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai/resolve/6450bb584cef43ede3b514df48e301a832c6818b/majsoul-throne-2019.tar) | 54620160 | `c6e54d1b2cce000059573bb646201994986edf1bbf7d6b12d0726bad48dd9641` |

Both archives match the publisher's LFS sizes and SHA256 values. The 2019
archive was used for an additional compatibility probe; it is not counted in
the selected training corpus. The 2026 archive contains 23,182 files, of which
23,179 are unique structurally complete four-player matches. Three lack a
round result and were excluded. The saved corpus has 244,242 rounds and
24,666,562 events, dated 2026-01-01 through 2026-02-03 by game UUID.

The room classification is publisher evidence, not independent verification
of every player's rank. These MJAI files contain neither original official
operation lists nor individual rank metadata. The dataset license label is
`other`; its tooling license does not grant ownership of game records.
The cache preserves the dataset card and its hash, archive hashes, member
names, game UUIDs, compressed/decoded/canonical-event hashes, and exclusions.

MJAI training masks are explicitly marked `riichienv-reconstructed`, with
engine version `0.4.10`; they must not be described as original server masks.
The MJAI adapter is separate from `policy_extract.cjs`, whose requirements
for recorded official operations remain in force. Kan suffixes and uncertain
response labels are excluded as documented in the conversion guide.

All full games and weights stay under ignored `.local/`; the checked-in
[validation summary](benchmarks/policy-mjai-20261010.json) contains aggregate
counts and hashes only. No account session, credentials, or private replays
were used to acquire this public corpus.

## Additional original-format samples and bulk access status

After the user separately requested at least 10,000 original-format games,
two more public decoded `ResGameRecord` JSON files were downloaded from
`0num4/vscode-devcontainer-test`, fixed commit
`c0a188685da2206684d94d270475c473635dbae8`. They retain `head` and decoded
`.lq.GameDetailRecords` instead of MJAI events. Both are ranked Jade South
(`mode_id = 12`) with player level IDs preserved in the header.

| Game | Source bytes | SHA256 | Verified training samples |
| --- | --- | --- | --- |
| [230921-0a39a19b-4820-4b40-9fda-dd5481d023e4](https://raw.githubusercontent.com/0num4/vscode-devcontainer-test/c0a188685da2206684d94d270475c473635dbae8/cpp/parseGameRecordAndAnalyze_py/paifu/mahjongsoul_paifu_230921-0a39a19b-4820-4b40-9fda-dd5481d023e4.txt) | 488188 | `c929fba0bb83c18a80f3496a26527c41c6a2841e6c8e6ec1c2eb64aa8f28d7e3` | 326 |
| [230921-2e8495ad-c9df-4b0f-9f10-dd354b9daeeb](https://raw.githubusercontent.com/0num4/vscode-devcontainer-test/c0a188685da2206684d94d270475c473635dbae8/cpp/parseGameRecordAndAnalyze_py/paifu/mahjongsoul_paifu_230921-2e8495ad-c9df-4b0f-9f10-dd354b9daeeb.txt) | 820662 | `5422f57784e3301969c902bc43cdb28e0550a118d18a1536730b547d28f38e75` | 536 |

The repository has no discovered LICENSE; no redistribution grant is inferred.
Original files, normalized copies and extraction audits are under
`.local/policy-official/public-samples/`. Both passed the official importer,
replay extractor and training reader. Their metadata and verification are
recorded in [the original-format status report](benchmarks/policy-official-20261010.json).

**The 10,000-game original-format acquisition is not complete: 19 complete
official Throne raw games are durably archived as of 2026-10-11.** Explicit
CDP authorization succeeded in the current conversation. Native method-name
diagnostics identified the authenticated lobby connection, and the official
replay UI established the exact current client version
`WebGL_2022-0.16.283`. The legacy `web-0.11.252` value produced official error
151 (outdated client version); it was not evidence of denied replay access.

The three requested UUIDs ending `5e52b032`, `7c4aff37`, and `aeb23722`
all returned complete original responses with official `mode_id=16` headers.
Together they contain 3,256 Record events and 32 rounds. Their exact response
frames, original `GameDetailRecords` Wrapper bytes, decoded headers, pinned
schema and SHA-256 manifest are preserved under
`.local/policy-official/archive/`. The third game's final `RecordNoTile`
explicitly has `gameend=false`; its recorded old scores plus deltas exactly
match the completed header. Archive validation uses that score equality
instead of requiring a true flag. Multiple draw settlements remain rejected
until their aggregation semantics are verified.

All three requested raw games also passed the existing importer, extractor
and training reader. The first two produced 1,284 explicit labels; the third
produced 610 samples (605 explicit, 4 accepted-result labels and 1 inferred
pass). All samples have valid legal-action targets and finite features.
The combined count is 1,894 from the independent verification runs; this
training check covers those three games only. Full evidence is in
`.local/policy-official/probes/three-game-verification.json` and
`probes/training-verification/{report,third-report}.json`.

The first 50-game bulk batch was not durably exported before a browser page
reload and is not counted. Following explicit user approval, the local-only
archive bridge ran successfully: the official game page passed its health
check and posted a durable batch spool containing 16 complete responses and
one official error response. Fifteen games were archived immediately. The
remaining successful response was recovered offline after adding strict
validation for recorded riichi deposits awarded to the sole leader after
the final draw. Its original bytes were not changed. The archive/batch/bridge
suite now passes 40 tests; the browser driver has 29 passing mock tests.

The official server stopped the batch with error **540**. The current Unity
client's official error table maps this to “超出牌谱拉取限制，请稍后重试”
(replay retrieval limit exceeded). Error 541 separately denotes missing log
viewing permission. The official text does not specify a quota or recovery
time. The collector and local bridge are stopped, with no automatic retry
scheduled. Original resource packages, hashes, the exact mapping and an
offline decoder are preserved in
`.local/policy-official/probes/error-540/`; the live batch and offline recovery
reports are in `probes/bulk-20261011*.json`.

A final read-only audit rechecked all 19 original responses, bodies and
headers against their file hashes, unique UUIDs, unique body hashes, the
pinned queue and schema, and the archive's structural validation rules.
All 19 are official mode 16, containing 190 rounds and 18,797 Record events,
with no unknown schema fields. `final-verification.json` correctly reports
`insufficient_games`: 9,981 additional complete games are still required.
The 23,179-UUID queue under `.local/policy-official/requests/` is an index;
neither pending IDs nor the separate MJAI corpus count toward the raw target.

Future retrieval should preserve both the full `ResGameRecord` response and
any original body supplied through `data_url`. A body-only `GameDetailRecords`
blob lacks the header needed to validate room, player levels and match rules.
Even original records may omit some operation lists; download completeness
and training-window coverage must be checked separately.

### Archive original responses locally

`scripts/policy_official_archive.py` is an offline archive gate, not a login
or browser downloader. It accepts raw `ResGameRecord` protobuf responses or
their original WebSocket response frames. It saves the exact response bytes,
original `GameDetailRecords` Wrapper, decoded header, pinned schema, and a
manifest of file hashes. Only complete four-player ranked Throne games
(`mode_id` 15/16) pass this gate; the public Jade JSON samples above are not
counted toward this archive.

```sh
python3 scripts/policy_official_archive.py \
  --input /path/to/original-response.bin --format ws-response \
  --expected-uuid GAME_UUID \
  --schema .local/policy-data/liqi-0.11.243.w.json \
  --output .local/policy-official/archive
```

If the response contains only `data_url`, also supply `--body-file` with the
downloaded original bytes and `--body-url` with that exact URL. The CLI does
not fetch it. A URL without its body never counts as a complete game. The
archive verifies existing files when reopened and rejects conflicting UUIDs,
duplicate bodies under different UUIDs, and corrupted saved content.
These structural checks do not replace a full rules replay or prove that
every decision has a recorded legal-operation list.
