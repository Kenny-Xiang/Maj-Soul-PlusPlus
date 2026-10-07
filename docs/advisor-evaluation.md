# Offline advisor evaluation

The comparison runner evaluates identical public snapshots against two advisor
source versions. It never opens the game, connects to game servers, or submits an
action. It measures reproducibility, rule regressions, recommendation changes,
and local calculation time; it does not establish stronger play or calibrated
win probabilities. The latest v11 policy results appear in the final section;
earlier sections retain their historical comparison context.

## Historical: exact live ranking and decision-local reuse (v8, 2026-10-05)

The following measurements used v8; its ranking and cache optimizations are
also retained in v9. Relative to baseline `69c693f250ba13eeded39ae2b0780b4b8b0dd66d`,
the live worker requests an exact three-candidate ranked prefix, while every
legal candidate still receives the complete policy evaluation and terminal
ledger. Fixed-anchor epsilon groups crossing the cutoff are resolved in full;
lower groups skip only ranking work that cannot affect the prefix. Online
`candidates[rankedCandidateCount:]` retains every other candidate in input
order, **not rank order**. Offline `advise(state)` still returns a full ranking.
The existing internal best-only windows remain best-only.

The coarse projected policy now reuses immutable `Outcome` values within the
existing decision-local cache. Keys contain all derived inputs without
rounding, including event order, seat, progress, separate ron/tsumo values,
discard risk, survival and terminal transfers. Cache hits still check
cancellation. Search coverage, risk terms and the two-second budget are unchanged.

All 57 existing fixed states plus five frozen public slow-decision snapshots
were compared in fresh interpreters. Across **62 states and 620 candidates**,
the best action, exact first three complete candidates and explanations,
every public candidate field, and every private root ranking input matched
the baseline exactly. The default full-ranking API also matched the complete
baseline ordering. Only elapsed time, explicit prefix metadata and live tail
order are intentionally different. The five snapshots are committed in
`tests/fixtures/advisor_performance_logged_cases.json`; they contain public
decision inputs, not opponent hidden hands.

### Performance measurements

[Machine-readable results](benchmarks/advisor-performance-20261005.json) include
per-case first/cached/warm timings, exact source-file and fixture hashes,
environment, equivalence checks and a separate cache diagnostic. Timings use
`perf_counter` around `advise`, excluding imports and process startup.

Warm-suite measurements use a fresh interpreter per version and suite, one
identical ordered warmup pass, then three measured passes. First-call
measurements use a fresh interpreter per version **per case**, alternating
version order; each is followed immediately by one cached call. These are
different cache workloads, so the two tables should not be combined.

| Warm suite | Baseline median / P95 / max ms | Live optimized median / P95 / max ms |
|---|---:|---:|
| Fixed 57 states, 171 samples | 41.93 / 774.28 / 1045.04 | 32.06 / 727.98 / 1042.08 |
| Five recorded slow states, 15 samples | 736.69 / 1158.95 / 1158.95 | 613.83 / 915.96 / 915.96 |

| Isolated case workload | Baseline median / P95 / max ms | Live optimized median / P95 / max ms |
|---|---:|---:|
| Fixed 57, first call | 115.67 / 711.38 / 970.61 | 52.06 / 685.35 / 945.04 |
| Fixed 57, immediate cached call | 23.03 / 582.48 / 837.60 | 11.30 / 559.88 / 784.49 |
| Five slow states, first call | 702.20 / 1107.77 / 1107.77 | 610.33 / 919.08 / 919.08 |
| Five slow states, immediate cached call | 285.93 / 416.38 / 416.38 | 134.79 / 409.63 / 409.63 |
| Ordinary discard without kan/kita offered, 40 states, first call | 153.88 / 362.03 / 365.80 | 52.50 / 159.51 / 270.34 |
| Same 40 states, immediate cached call | 22.76 / 40.22 / 56.03 | 8.27 / 35.60 / 53.88 |
| Kan/kita offered, 11 states, first call | 702.20 / 1107.77 / 1107.77 | 619.62 / 945.04 / 945.04 |
| Same 11 states, immediate cached call | 319.61 / 837.60 / 837.60 | 174.44 / 784.49 / 784.49 |

This is not a universal per-case speedup. Nine of 62 warm per-case medians
increased. The largest was `threat-meld-count-0`, 32.27 to 88.20 ms;
`last-draw-after-pass` increased from 10.32 to 19.49 ms. A separate same-order
diagnostic found zero shanten cache misses for the former baseline versus
5,450 misses after prefix ranking, confirming changed cross-case cache reuse.
For that same state in isolation, first-call time improved from 351.01 to
91.41 ms and immediate repeat from 28.40 to 7.47 ms. The other small regression
has no established cause and remains reported. No cache size was increased
to hide these effects. All five slow-state medians improved, but the fixed
suite maximum remains about 1.04 seconds and the sample is not a worst-case
guarantee. P95 equals the maximum for the five-state sample by nearest rank.

To reproduce the warm comparison, use the combined-fixture construction in
the v8 section below, then:

```sh
.venv/bin/python scripts/advisor_compare.py \
  --baseline 69c693f250ba13eeded39ae2b0780b4b8b0dd66d \
  --current-ref d40aa460f3b1854d9b0402317d78b969ffb15ad3 --ranked-limit 3 \
  --fixtures build/current-policy-v8/combined-cases.json \
  --warmups 1 --repeats 3 --output build/prefix-fixed.json
.venv/bin/python scripts/advisor_compare.py \
  --baseline 69c693f250ba13eeded39ae2b0780b4b8b0dd66d \
  --current-ref d40aa460f3b1854d9b0402317d78b969ffb15ad3 --ranked-limit 3 \
  --fixtures tests/fixtures/advisor_performance_logged_cases.json \
  --warmups 1 --repeats 3 --output build/prefix-slow.json
```

For isolated first/repeat timings, run one `--case ID` at a time with
`--warmups 0 --repeats 2`; inspect each case's first and second `samplesMs`
separately. The checked-in run alternated baseline/current execution order
by case using `run_version`, whose worker always starts a fresh interpreter.
The runner compares the advertised ordered prefix and all candidate fields
by action ID, including candidates outside that prefix.

### Overlay and validation

The right panel now focuses on action/tile, post-call discard, current policy,
shanten/effective unseen tiles, correctly scoped risk and conditional win
points. It shows at most one alternative. Win probability, score and loss
diagnostics remain calculated and logged; normal timestamps/counters and
zero-error diagnostics are hidden. Furiten, no-yaku, four-riichi/four-kan
termination and unverified actions take precedence over generic reasons,
including on narrow screens. Four-riichi termination suppresses the
inapplicable later forced-discard explanation. Click-through and the left
column are preserved.

All **307 advisor/worker/benchmark tests**, **32 protocol Node tests**,
**7 offline overlay DOM tests**, and **6 formatter/logging tests** passed.
New regressions cover crossing ties, raw precision, full candidate retention,
cache keys and lifetime, cancellation/deadlines, slow recorded states and
priority reminders. Offline browser rendering checked 1280/800 px ordinary
and furiten states, incomplete history/hand, unverified actions, disconnection,
four-riichi termination and long rivers. Ordinary font sizes improved from
12 to 13 px at 1280 and 10.5 to 11.5 px at 800; long rivers still shrink to
9 px at 800 because the unchanged left column determines panel height.

Saved browser evidence: [ordinary 1280 px](benchmarks/overlay-20261005/01-ordinary-1280.jpg),
[ordinary 800 px](benchmarks/overlay-20261005/02-ordinary-800.jpg),
[furiten 800 px](benchmarks/overlay-20261005/04-furiten-800.jpg), and
[all layout checks](benchmarks/overlay-20261005/layout-checks.json).
The screenshot manifest records renderer, source and artifact hashes. These
are offline component captures; ordinary/furiten packets reuse the saved v8
computed results, which the equivalence checks reproduced. Exceptional and
long-river views are display fixtures, not claimed live-game observations.

Native WebKit checks were attempted but remain **unverified**: the overlay
test encountered sandbox-extension failures and `WKErrorDomain Code=5`, and
the native protocol test received no packets before its deadline. Browser
checks do not establish native rendering, fullscreen or live-game background
behavior. The running application and primary checkout were not updated.

## Historical: explicit current policy and semantic ties (v8, 2026-10-05)

The v8 model is `public-information-actions-ev-v8-current-policy` and is
still uncalibrated. This change builds on the completed v7 work in PR #21,
commit `0415bd3441b08b3699e8ae19223786d5ae8db1ed`. Its source was checked against
the frozen v7 snapshot before comparison; it is not compared with an older v6
HEAD merely because the primary checkout was restored after PR creation.
The v7 and earlier sections below retain their historical measurements.

The primary score now contains terminal payments and applicable action costs,
without an additive efficiency reward. `currentStrategy` distinguishes
`attack`, `fold`, and already-riichi `locked` decisions. A current fold consumes
held physical tiles, earns no self-win income and takes noten settlement on a
surviving ordinary draw. It is offered at every shanten level, including when
no held tile is risk-free. Its first discard must minimize current expected
loss over all legal discards; this preserves v7's guard against justifying a
dangerous probe using the safety information obtained only if it survives.
Future changes of safety and re-entry are frozen within this approximation;
each actual new snapshot is evaluated afresh.

`futureFoldProbability` describes later retreat while currently continuing;
it is zero when the current choice is already a fold. Replacement branches
record their own current policy and contribute any branch fold to the root's
future-fold diagnostic. A legal server-provided win still takes priority.
Pure defensive calls do not pay the existing no-yaku attack penalty; that
penalty is now applied before policy and post-call-discard selection.

All action windows compare full-precision scores. Only floating-point ties
(absolute tolerance `1e-9`, relative tolerance `1e-12`, fixed best anchors)
proceed through expected adverse payments, current loss, usable physical
safety stock, self-win probability, scored ron waits, reachable shape and
effective count. Remaining ties compare the expected increase in effective
tiles after a same-shanten exchange. Tile encoding is the final stability
fallback. There is no blanket honor-discard rule or new push threshold.
See [the policy document](advisor-policy.md) for the exact ordering and bounds.

Coarse distant-hand valuation also separates tsumo and ron. An unidentified
closed ron route cannot obtain income from menzen-tsumo yaku; its ron estimate
is conservatively zero. Future shape changes may still establish a real yaku.
Known projected yaku and sanma payments use the corresponding actor's score.
This does not fully enumerate later discards or eliminate assumptions that
projected yaku and dora can be retained.

### Reproduction and measured results

The 49 existing cases and eight recorded public snapshots form 57 states.
The historical v6 outputs for the eight snapshots were also reproduced at
`150dfd9`: all full outputs matched the original recording except elapsed time.
The committed log fixtures contain complete public decision inputs and no
assertion that the subsequently observed loss determines the best action.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_advi*.py'
node --test tests/test.cjs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_python.py
.venv/bin/python - <<'PY'
import json
from pathlib import Path
output = Path('build/current-policy-v8')
output.mkdir(parents=True, exist_ok=True)
names = ('advisor_cases.json', 'advisor_threat_cases.json',
         'advisor_phase_cases.json', 'advisor_policy_logged_cases.json')
cases = [case for name in names for case in
         json.loads((Path('tests/fixtures') / name).read_text())['cases']]
(output / 'combined-cases.json').write_text(json.dumps({'schemaVersion': 1, 'cases': cases}))
PY
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_compare.py \
  --baseline 0415bd3441b08b3699e8ae19223786d5ae8db1ed \
  --fixtures build/current-policy-v8/combined-cases.json \
  --warmups 1 --repeats 5 --output build/current-policy-v8/comparison.json
```

All **285 advisor/worker/benchmark tests passed**, including the original
one-second representative replacement test and unchanged two-second budget.
Node protocol tests passed 32/32; Python formatting/logging tests passed 6/6.
New checks cover raw/display ties, candidate-order and suit permutations,
honor-pair/yakuhai/kokushi controls, defense without genbutsu, valuable attack,
policy metadata, physical inventory, cancellation and isolated caches.
Existing payment proofs were retained; tests formerly expecting an efficiency
payment now check its exclusion from money and its secondary shape role.

Each version ran in a fresh interpreter, with one full warmup and five
measured passes: 285 samples per version. Every case retained its expected
availability, all inputs were unchanged, and repeated full outputs were
identical except elapsed time.

| Source | Median ms | P95 ms | Maximum ms |
|---|---:|---:|---:|
| Frozen v7 / PR #21 (`0415bd3`) | 14.336 | 702.877 | 1092.705 |
| v8 source | 41.417 | 758.158 | 1028.046 |

The measured source SHA-256 values (the runner's whole-`src` digest) are
`fdbf1ca454b995653c0bdee98599a77cda7c6f323fb16857d9a69526a1f77988` for v7 and
`ed07ca86c60f0820c46f6a2f47a7f35991e7bc990dea7c646adc709fd520f939` for v8.
These measurements include the additional policy/tie work; they are not a
general speedup claim or a worst-case timing guarantee. Exact optimizations
reuse scoring and structural results, skip impossible physical draws, and
skip sorting losing nested groups. Identical DP ledgers require no further
tile distinction. Equivalence and cache tests protect those shortcuts.

Across 552 current candidates, terminal mass differs from one by at most
`2.45e-15`, displayed score reconciliation differs by at most `4.55e-13`, and
the final rounding adjustment is below 0.05 points. No candidate includes
`efficiencyReward` in its monetary breakdown; 16 candidates select a current
fold. These are accounting properties, not empirical probability calibration.

### Recorded decisions and remaining limitations

Eight of the 57 states changed the recommendation or post-call discard:
`river-furiten`, `pon-yakuhai`, `phase-no-own-draw`, `phase-two-own-draws`,
`phase-early-quiet`, and logged decisions 766, 798 and 1398. A yakuhai pon
still wins but its follow-up changes from 1z to 2s; the complete terminal
estimate values 2s at 1220.6 versus 1z at 1167.7, without forcing the lowest
shanten by an additive reward. The weak quiet-hand control now selects a
current fold, while the valuable live-tenpai control continues attacking.

The advantage below compares both choices under v8, not scores across models.
Small advantages are sensitive to the disclosed approximations.

| State | v7 → v8 choice | v8 net advantage | Main reason |
|---|---|---:|---|
| river-furiten | 1z → 4s | 3.897 | expected draw transfer +44.34 offsets lower win income and higher future costs; it does not increase win chance |
| pon-yakuhai | pon, then 1z → 2s | 52.87 | expanded post-call window prefers its complete terminal estimate; the aggregate report only stores the selected follow-up |
| phase-no-own-draw | 7z → 7p | 0.068 | full-precision net values differ although both display -919.8; no future self-draw or self-win income |
| phase-two-own-draws | 2m → 7p | 50.340 | current fold reduces current/future loss by 40.30/77.32, paying more noten cost |
| phase-early-quiet | 4p → 1s | 85.353 | current fold reduces current/future loss by 33.80/59.55 and gives up its small attack income |
| logged 766 | 3s → 6z | 0 | same-shanten shape improvement at a true monetary tie |
| logged 798 | 2s → 6z | 0 | same-shanten shape improvement at a true monetary tie |
| logged 1398 | 7s → 9s | 515.561 | attack earns 561.41 more win income and pays 540.09 less future loss, accepting 674.96 more current loss |

| Recorded turn | Original v6 | Frozen v7 | v8 | Current v8 policy |
|---|---|---|---|---|
| 766 | 3s | 3s | 6z | attack |
| 786 | 2p | 2p | 2p | attack |
| 798 | 2s | 2s | 6z | attack |
| 906 | 4p | 6z | 6z | attack |
| 1358 | 5p | 5p | 5p | attack |
| 1386 | 9p | 9p | 9p | attack |
| 1398 | 7s | 7s | 9s | attack |
| 1410 | 2p | 2p | 2p | attack |

For 766 and 798 the compared candidates have equal modeled net outcomes;
same-shanten improvement breaks the tie in favor of discarding 6z. In 786,
the modeled safety and shape criteria still tie, so 2p remains a stable
fallback and the explanation identifies the modeled equivalence. Valuable
honor sets/pairs and actual kokushi routes are separate regression controls.

The 906 recommendation was already corrected by v7 and is not claimed as a
new v8 fix. Its two-shanten 4p continuation now earns 707.58 points of expected
win income instead of v7's 1962.33, while still paying 539.39 points of future
discard loss. Its v8 score is 174.23, below the one-shanten 6z route at 1740.49.

For 1358, two-shanten 5p still narrowly leads one-shanten 9s:
684.3227 versus 673.3774, only **10.9453 points**. Its win income is lower
(1074.54 versus 1119.38); lower estimated future discard loss (545.13 versus
647.33) helps offset that. The gap shrank from about 1241.5 in v7, but model
error can easily exceed the remaining gap. Coarse future discard/dora
retention and exact one-shanten waits still have different precision. This
does not prove 5p is the stronger real choice or that lower shanten must win.

**1410 still recommends attacking with 2p.** Its v8 score is -4597.0390,
versus -4904.8593 for attacking with 1s and -5163.6998 for attacking with 9s.
The eligible current-fold first discard is 9s, with fold score -6450.3047.
The 2p path now earns 482.40 points of win income (6.89% displayed win chance,
7000 conditional points), pays 1257.20 current and 2859.72 future discard
loss, plus risk preference and other terminal payments. It receives no
efficiency income. The pure-fold approximation can understate real defensive
value by forgoing accidental wins and safe tenpai; coarse attack can overstate
future shape/dora retention. No result here proves avoidance of the recorded
18000-point loss or identifies a counterfactual winning discard.

Native replay and overlay remain **unverified**: this source again produced
empty replay packets and `WKErrorDomain Code=5` with sandbox-extension failures.
Algorithm and Node passes are not a native UI pass. Local comparison inputs,
raw candidate ledgers, source hashes and validation logs are retained under
`build/current-policy-v8/` and are not committed. This work is delivered as a
PR dependent on #21; the primary checkout stays clean. The installed Desktop
App remains v7 until explicitly replaced; a source PR does not update that
frozen runtime. Built-v8 runtime validation and delivery status are reported
separately from source tests.

## Historical: policy and terminal ledger (v7, 2026-10-05)

The v7 model is `public-information-actions-ev-v7-policy-terminals` and
remains explicitly uncalibrated. The sections below this one are historical
results, including their historical test counts; they do not describe the
current future-risk or fixed-tenpai-bonus behavior. Detailed assumptions are
in [the policy document](advisor-policy.md), [calibration data contract](advisor-calibration.md)
and [explicit endgame input contract](advisor-endgame.md).

The physical `5p` regression uses the reachable four-round/called-white history,
including discard steps and moqie. Before the change it returned 0.02025 deal-in
probability and 20.25 points of loss, despite no physical ron shape remaining.
It now returns exactly zero for both. Sequence, pair, chiitoitsu, sanma,
red-five, four-group tanki and kokushi exclusions are covered; ordinary suji
or a single wall does not imply absolute safety.

Dama and riichi now use the same bounded ready-policy ledger; only dama may
fold. Folding consumes the original hand's finite stock, loses subsequent
wins and tenpai fees, and still pays discard risk. One-shanten routes include
ineffective draws, the actual ready discard and maintenance of ready hands.
Two-shanten and beyond compare coarse paid progress with a complete greedy
fold starting from a minimum-current-loss legal discard (including all ties).
That fold sacrifices win income and efficiency, instead of justifying a risky
probe with hypothetical future safety. Kokushi retains its missing-orphan/pair
state model. This does not exhaust all later retreat/re-entry policies.
Future public evidence, actual miss identities, re-entry after folding and
newly acquired safety are not exhaustively expanded. Fold-stock risk is
frozen and can conservatively miss safety established by a subsequent draw.

Each candidate exposes mutually exclusive `terminalProbabilities`: self win,
current plus future deal-in, opponent tsumo, other-player ron, ordinary draw,
and known abortive draw when applicable. `futureFoldProbability` is diagnostic,
not another ending. Self-payment on enemy tsumo and visible pao is separate
from the winner's deposits. The old residual competition hazard is charged
once and split 40%/60% between tsumo and other ron: these remain unfitted
constants, and their per-event allocation is not constrained by the actor's
actual draw opportunity. Unknown pao source and pao honba use disclosed payment
lower bounds. Draw fees enumerate independent frozen opponent readiness with
3000/2000-point four-/three-player pools, only on surviving ordinary draws.
The old fixed `lateTenpaiReward` has been removed. Efficiency and rank risk
preferences remain heuristics separate from monetary terminal outcomes.

There is no sufficient labelled corpus for empirical calibration: the
available recording has 60 frames/48 events (steps 63–110), no opening or
terminal event, and 16 hidden tiles among 22 draws. The 49 fixtures do not have
per-decision hidden-hand labels. `scripts/advisor_calibration.py` audits this
limitation and provides public-only extraction and whole-match/time-separated
train/validation/test evaluation for separately labelled readiness, conditional
ron and payment. No coefficients were fitted or deployed from this corpus.
`round.isFinal: true` enables bounded rank preferences only when supplied by a
trusted caller; the live collector does not yet provide match-length metadata.

### Reproduction and measured results

The starting advisor baseline is `150dfd9`. During implementation another chat
committed the pre-existing white-dragon concealed-kan change as `764b69b`;
that commit's advisor is byte-identical to the baseline and its core changes
were preserved. Comparisons use the explicit original ref, not a moving HEAD.

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_advi*.py'
.venv/bin/python scripts/advisor_calibration.py audit --output build/strategy-v7/calibration-audit.json
# all-cases.json concatenates the three existing advisor fixture case arrays.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_compare.py \
  --baseline 150dfd9 --fixtures build/strategy-v7/all-cases.json \
  --warmups 1 --repeats 5 --output build/strategy-v7/comparison.json
```

All **232 advisor/worker/benchmark tests passed**, including original one-second
representative replacement and two-second cooperative budget checks. Node
protocol tests passed 32/32 and Python formatting/logging tests 6/6. The full
fixture suite checks input immutability, legality, terminal mass, red/sanma
rules, score reconciliation, cache isolation and cancellation. The original
baseline passed 176 advisor-related tests before edits. Frozen App verification
skips only the two tests requiring a Git checkout/Python CLI subprocess;
`unittest.mock` and `platform` are explicitly bundled for offline verification.

The isolated comparison used 49 states, one warmup and five measured passes,
245 samples per version. All states retained their expected availability and
all repeated full outputs were deterministic (apart from elapsed time).

| Source | Median ms | P95 ms | Maximum ms |
|---|---:|---:|---:|
| Original v6 (`150dfd9`) | 4.832 | 507.971 | 760.504 |
| v7 working source | 9.412 | 723.153 | 1096.508 |

The extra policy calculation has a measurable cost; the two-second limit was
not raised. Decision-local public-price/risk/policy tables avoid repeated
identical work. Fold-table compression was independently compared on 500
random inputs/24,761 suffixes: maximum probability discrepancy 1.11e-15 and
maximum payment discrepancy 2.91e-11 points. Across all fixed-state candidates,
terminal mass differs from one by at most 2.45e-15. These checks establish
accounting/reproducibility, not calibrated frequencies or stronger play.

### Recommendation changes and controls

Five states changed their recommendation or post-call discard. The advantage
below compares both actions under v7; positive component deltas favor the new
choice. Raw per-candidate ledgers are retained in `comparison.json`.

| State | v6 → v7 | v7 score advantage | Main ledger differences (points) |
|---|---|---:|---|
| closed-tsumo-only-tenpai | discard 1s → 1z | 106.1 | draw transfer +105.2; win income −81.0; efficiency +68.1; future discard loss +12.8 |
| new-riichi-changed-waits | discard 9m → riichi 7m | 194.6 | win income +867.1; deposit −580.4; draw transfer −88.1; future dama/forced risk changes separately |
| chi-called-low-yakuhai | same chi, discard 2z → 5p | 77.0 | draw transfer +653.3; win income −416.7; future discard loss −62.7; efficiency −56.8 |
| phase-one-own-draw | discard 7z → 7p | 0.1 | draw transfer +0.052, future discard loss +0.004; a near tie sensitive to rounding/approximations |
| phase-two-own-draws | discard 7z → 2m | 10.2 | current discard loss −40.3; draw transfer +38.8; efficiency +12.0 |

The coarse-fold regression was added after a reproducible intermediate
model defect: forcing a remote hand to keep pushing could prefer a cheap
immediate deal-in merely because it terminated an expensive projected future.
The complete greedy-fold alternative restores the early-riichi control to
safe 1s, and gets neither future win income nor an efficiency reward. Current
root risk still absorbs future outcomes once; it is not erased or penalized
a second time. Passed-tile evidence remains restricted to future survivors.

| Requested control | v6 → v7 result | v7 accounting |
|---|---|---|
| early quiet | 4p / 98.2 → 4p / −530.2 | current loss 33.8; future loss 340.1; opponent tsumo 92.8; draw transfer −144.2; efficiency 136 |
| early riichi | 1s / 96.1 → 1s / −2852.2 | current hit/loss 0; committed fold, future loss 2027.2; no win or efficiency income |
| no own draw | 7z / −25.9 → 7z / −919.8 | hit 1.72%, loss 22.49; all candidate win/efficiency terms remain zero; draw transfer −889.3 |
| late valuable tenpai | 1z / 2414.0 → 1z / 1342.5 | win 23.48%, current hit 8.38%; win income 1335.8; future loss 361.7; actual draw transfer +517.9 |

The late valuable hand still accepts risk to preserve tenpai, but no longer
gets the old unconditional 1017.9-point bonus. Negative early scores now also
reflect projected future payments; the score scale is not comparable to v6
as if only the action quality had changed.

Native replay and overlay tests remain **unverified**, with the same baseline
failures on both `150dfd9` and `764b69b`: empty replay packets after about 20 s,
and `WKErrorDomain Code=5` with sandbox-extension denials. Current source
reproduces those failures. No extra permissions or real game connections were
used. Logs, bundle source hashes, build diagnostics and desktop-delivery checks
are preserved under `build/strategy-v7/`; the bundle must be rebuilt and
verified as a whole, because copying its reference source does not update the
frozen runtime.

## Public opponent evidence (v6, uncalibrated)

Opponent risk now exposes three separate quantities in `opponentRisks`:
`tenpaiProbability`, `conditionalRonProbability`, and `lossPoints`. The first
two multiply to the single-opponent hit estimate (before display rounding).
The design follows the decomposition in
[Mizukami and Tsuruoka (2015)](https://www.logos.t.u-tokyo.ac.jp/~tsuruoka/papers/cig2015mizukami.pdf),
DOI 10.1109/CIG.2015.7317929; no trained parameters or performance claims from
that paper are imported.

The existing river-length/0–3-group readiness curve and 65% cap remain.
Concealed kans count as completed groups, without opening the hand. Four
groups imply structural tanki readiness, not a known legal ron wait: the
singleton uses an uncalibrated uniform unknown-tile prior, physical pair
exclusions, and no sequence-based suji/wall discount. Its mutually exclusive
tile-type probabilities sum to at most one. Bonus tiles and dealer status
affect payment, not readiness; `_event_survival` consumes the same readiness
estimate without an additional open-hand penalty.

An open hand without identified yaku gets a 0.6 eligibility weight. This is
an evidence discount, not a measured yaku probability; 1 means no discount,
not proof of legal ron. Two/three same-suit numerical groups support a
0.25/0.5 flush mixture only when every public group is compatible, including
concealed kans. Off-suit tiles retain the ordinary branch. Four groups can
confirm toitoi, tanyao and compatible honitsu/chinitsu. Route hits and their
payments are mixed together, rather than averaging han across scoring caps.
Missing identified yaku never becomes a false-safe exclusion: hidden yaku,
river-bottom/robbery events and other unenumerated public yaku remain outside
this approximate eligibility model. Hidden discard styles and call times are
not fabricated, and three calls never imply certain readiness.

Conditional payments include the discarded tile's known dora and red bonus,
public meld-fu floors, and the known pair dora/fu on a four-group tanki hit.
The concealed singleton's red identity remains unknown. Existing yakuman/pao
payment bounds, honba and exclusion of the winner's existing deposits remain.
These are incomplete public-value estimates, not exact hidden-hand scores.

`tests/fixtures/advisor_threat_cases.json` adds 19 synthetic public states with
legal tile inventories, called-river/source records and achievable turn counts.
They cover early/late weak and valuable hands, early riichi, 0–4 open groups,
unknown/confirmed yaku, suit evidence, visible bonus/red tiles, concealed kan,
dealer status, sanma North and multiple threats. Calls consume fewer normal
draws, so the matched ten-discard 0–4-group series has `left=29..33`; identical
river counts are not incorrectly paired with identical wall counts.

On 2026-10-04, comparison with `c207045` used the existing 24 states plus these
19 states, one warmup and five measured passes (215 samples per version).
Baseline median/P95/max were 5.999/481.739/717.691 ms; v6 measured
6.192/517.220/747.326 ms. Every repeat was deterministic; availability and
root recommendations were unchanged. For the four-group `4p` probe, seat 1's
hit estimate changes from 6.5% to 2.74% despite structural readiness becoming
100%: the new model respects the narrower tanki shape. The two-group unknown
yaku probe changes from 5% to 3%, while identified yakuhai retains its full
weight. These are model changes, not accuracy or playing-strength evidence.

The sensitivity command below evaluates all 43 states at nine combinations of
eligibility weight 0.4/0.6/0.8 and flush step 0.15/0.25/0.35 (still capped at
0.5). No root recommendation changed versus defaults; candidate scores and
risk estimates remain parameter-dependent. This small, mostly clear-choice
corpus does not establish robustness near every decision boundary.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_threat_sensitivity.py \
  --output build/public-threat-sensitivity.json
.venv/bin/python scripts/advisor_compare.py --baseline c207045 \
  --fixtures tests/fixtures/advisor_threat_cases.json \
  --output build/public-threat-only-comparison.json
```

The combined report is `build/public-threat-comparison.json`; it uses the
concatenated `cases` arrays of both fixture files. All 163 advisor/worker/
benchmark tests, 31 JS tests and 6 formatter/logging tests passed. Native
WebKit replay and overlay checks remain unverified: both v6 and unchanged
`c207045` reproduce empty replay messages / `WKErrorDomain Code=5`, alongside
sandbox-extension failures. No extra permissions or game connections were
used. The two-second cooperative deadline, cancellation, stale-snapshot
rejection, scoring-cache isolation and confirmed-riichi absorption regressions
remain covered.

## Efficiency rewards with remaining draw opportunities

The late unready-hand controls expose a separate scoring problem after the
opponent change: when no remaining own draws can reach tenpai, the full
`70 * (6 - shanten) + 2 * ukeire` bonus can still favor a riskier discard.
For `phase-no-own-draw`, all candidates are at least two shanten with zero
modeled win probability. The old score picks `1s` with expected deal-in loss
29 rather than `7z` with loss 22, because it still credits 272 efficiency points.

Unready candidates now share an opportunity coefficient within the same
discard set. Let `required` be at least one and otherwise the structural
shanten of the parent hand before discarding; `draws` is the actual future
own-draw count from the existing ordered event sequence. The coefficient is
`min(1, max(0, draws - required + 1) / required)`. It is zero below the necessary
advance count, partial just above that boundary, and saturates with additional
opportunities. Sharing it across the discard set prevents the common
420-point score offset from becoming a new candidate-specific incentive to
push. Calls and replacement children use their own resulting hands/events.

This structural lower bound is not proof that a legal tenpai is reachable;
live effective tiles, legal-discard restrictions and unknown future calls can
further constrain it. The saturation at `2 * required - 1` draws is an
uncalibrated design choice, not a measured probability. Ready-hand rewards and
the existing late-tenpai bonus retain their previous meaning. In particular,
no-yaku or furiten hands can still have exhaustive-draw tenpai value. Those
bonuses remain heuristic preferences, not a complete terminal settlement EV.
There is no new late-game multiplier on deal-in loss or opponent competition.

Five focused regressions and six fixed phase controls cover zero/one/two
remaining own draws, early quiet play, early riichi and valuable late tenpai.
The no-own-draw and one-own-draw controls now choose `7z`, reducing their
modeled immediate losses from 29 to 22 and 28 to 21 respectively. Both still
have zero modeled win probability; unreachable efficiency rewards disappear.
The two-own-draw control retains the safer `7z` while assigning partial credit
to progress. Early quiet play still chooses `4p`; adding early riichi still
changes it to safe `1s`. Late valuable tenpai keeps `1z`, four live waiting
copies and nonzero risk, instead of being forced to fold.

All 168 advisor/worker/benchmark tests, 31 JS tests and 6 formatter/logging
tests passed. Against unchanged `c207045`, three of the five new phase tests
fail as intended. Existing expanded-window, passed-discard, confirmed-riichi,
terminal absorption, cancellation and decision-cache tests continue to pass.
Native WebKit validation remains limited by the baseline-reproduced failures
described above; it is not counted as passing.

The final batch combines all three fixture files: 49 identical states, one
warmup and five repeats (245 measurements per source), with timing runs kept
separate from tests. Against `c207045`, baseline median/P95/max were
4.977/482.828/756.985 ms and the final model measured
5.150/522.338/766.551 ms. The isolated phase comparison against opponent-only
commit `96e8e93` measured 4.891/512.273/750.998 ms before and
5.079/516.009/757.602 ms after. Both comparisons were deterministic and retained
all availability statuses; only `phase-no-own-draw` and `phase-one-own-draw`
changed root recommendation. Reports with every candidate and score ledger are
`build/final-main-comparison.json` and `build/final-phase-comparison.json`.
The phase-only fixture set can be rerun with `--fixtures
tests/fixtures/advisor_phase_cases.json`; concatenate the three `cases` arrays
for the complete batch. These warmed samples on one machine are not a latency
guarantee or evidence of calibrated risk or stronger play.

## Run a comparison

From the repository root, using the existing development environment:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_compare.py \
  --baseline HEAD --warmups 1 --repeats 5 \
  --output build/advisor-comparison.json
```

The baseline is a Git commit or ref. The current version defaults to the working
`src` directory, including uncommitted source edits; `--current-ref REF` instead
evaluates a second committed version. The runner copies sources to temporary
directories and starts an isolated Python process for each version. It does not
switch branches, reset files, or reuse imports from the caller's `PYTHONPATH`.
Both versions use the same installed dependencies. Dependency changes require
separate environments and are outside this runner's comparison.

Use repeated `--case ID` arguments to select cases. Selection retains fixture
order. For example, compare the known upstream riichi fix against its predecessor:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_compare.py \
  --baseline 8046cf8 --current-ref 0ba7879 \
  --case new-riichi-changed-waits --warmups 1 --repeats 5 \
  --output build/advisor-riichi-regression.json
```

Generated reports belong in ignored `build/`, not Git. The JSON includes the
exact input snapshots, fixture hash, source hashes, resolved commit IDs, dirty
source paths, model strings, Python/platform/dependency versions, all candidate
fields, status, recommendation changes, candidate field changes, and timing
samples. Analysis outside an action window retains its `analysis` status and
`wait` action. Unexpected availability status or mutation of an input snapshot
fails the run instead of silently presenting that case as a successful sample.

Score components are derived from the advisor's rounded public fields:
estimated win income, weighted current deal-in loss, weighted forced-discard
loss, riichi cost, new-dora penalty, and a residual that reconciles these terms
with the reported score. The residual contains shape rewards, tenpai value,
action-specific adjustments, and rounding. It is not an independently validated
terminal-outcome value. Full original candidate fields are preserved alongside
this decomposition so a later model can expose more precise terms.

## Timing protocol

Each version receives one excluded warmup pass over the entire selected case
list, followed by five measured passes by default. The same case order and pass
counts apply to both fresh processes; caches persist within a process. This
measures a warmed repeated workload. Set `--warmups 0 --repeats 1` to include each
case's first evaluation, although earlier cases can still warm shared caches.
Neither mode measures app startup or fully independent cold calls per case.

`perf_counter` surrounds only `advise`; imports, input copies, process startup,
and report generation are excluded. The advisor's own `elapsedMs` is retained
separately. Per-case and aggregate summaries report median, nearest-rank P95
(`ceil(0.95 * count)` in one-based sorted samples), and maximum milliseconds.
Aggregate statistics give each selected case the same number of samples and
combine different workloads; inspect per-case figures before drawing latency
conclusions. With five repeats, per-case P95 is the maximum.

The baseline process runs before the current process, so machine load, thermal
conditions, and source-dependent cache behavior can affect differences. For
performance decisions, repeat runs with the two committed refs swapped and use
the same machine, dependencies, fixture selection, and repetition counts.
Repeated outputs are checked for changes other than `elapsedMs`; differing
outputs are retained in `changedRepeats` instead of hidden by averaging.

## Fixture coverage and regression plan

`tests/fixtures/advisor_cases.json` contains full synthetic snapshots adapted
from `test_advisor.py` and `test_advisor_actions.py`, plus the existing recorded
sanma snapshot from `turn.json`. The original 18 cases cover ordinary efficiency, a broad
one-shanten discard set, closed hands without ron yaku, discard and confirmed
riichi furiten, new riichi, opponent riichi, chi, pon, all three kans, red fives,
sanma North extraction, final-draw ordering, and waiting analysis. Their expected
status is an availability contract, not a label declaring an optimal action.

Confirmed counterexamples have the following acceptance criteria. Add assertions
with their corresponding fixes, keeping the independent benchmark PR green:

| Counterexample | Status at baseline `59a30d5` | Acceptance criterion |
| --- | --- | --- |
| `new-riichi-changed-waits`: `11223344556679m`, own river `1m`, server furiten, offered riichi discard `7m` | Fixed upstream in `0ba7879`; existing action regression covers it | Dama and new riichi both recompute furiten as false on the new `9m` wait; confirmed riichi still preserves server furiten. Do not freeze a probability. |
| `last-draw-after-pass`: seat 0 skips chi of seat 3's `9m`, `left=1` | Unresolved | Preserve self's final draw and self-draw chance on `6m`/`9m`; cover all seats, three/four players, passing and post-call order. |
| Wide-wait mathematical probe: unseen 54, 39 waiting copies distributed across multiple tile types, three opponents, one own draw, all result values 96000 | Unresolved; not a physically invalid full-state fixture | Probability remains in [0, 1]; conditional average stays within reachable point values and equals 96000 when all outcomes equal 96000. Old model returns 105600. Add a focused `_win_model` regression with the fix. |
| `closed-tsumo-only-one-shanten`: `123456m78p12s55z1z` | Unresolved | Direct `6p`, `9p`, or `3s` then discard `1z` branches have no ron value and retain self-draw value. Evaluate branch probability times its own value, preserve misses and remaining turns, and do not spend the same draw twice. |
| Broad one-shanten and red-five cases | Precision upgrade pending | Apply the same search precision to all candidates, enumerate effective draws and legal follow-up discards, update furiten and physical/red counts, and remain invariant to enumeration order. |

The direct-branch no-yaku assertion does not imply every possible later change
to that hand remains without ron yaku. Unit tests can verify rule calculations,
mass conservation, and deterministic accounting. Historical public snapshots
can assess stability and recommendation changes, but the historical continuation
after discard A is not evidence for the outcome of hypothetical discard B.
Probability calibration needs trustworthy labels with whole-match or temporal
train/validation separation. Long-run value comparisons need a rule-consistent
simulator, explicit continuation policies, paired initial conditions, and varied
opponents; those claims remain unverified by this benchmark.

## Verification

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  -m unittest discover -s tests -p 'test_advi*.py' -v
./scripts/test.sh
```

The benchmark tests validate fixture availability and physical counts, immutable
inputs, legal probability ranges, finite report values, nearest-rank statistics,
and an identical-ref comparison in isolated interpreters. The existing worker
tests continue to check that superseded snapshots never reach the overlay.
Timing is reported, not asserted as a universal latency guarantee.

## Turn-order and value-weight corrections (model v3)

The model now traverses the actual remaining own-draw/enemy-discard order for
pass, own discard, post-call discard, and pending enemy draws/calls/replacements.
Legacy snapshots without current-action metadata retain the documented
post-own-discard fallback. Unknown future calls are not simulated. The existing
competition factor is distributed across events so a full cycle retains its
original survival factor; no heuristic coefficients were fitted or retuned.

Every ready-hand event accumulates probability and points from the same weights.
The 39-of-54 equal-value probe now returns a conditional 96000 points, and the
final-draw pass case retains one own draw. A zero-probability horizon reports
zero conditional winning points without confusing a legal wait with no yaku.
The upstream new-riichi fix and confirmed-riichi furiten checks remain intact.

All 79 advisor-related tests, 31 Node tests, 6 formatting/logging tests, and both
offline WebKit suites passed. Comparing 18 cases with one warmup and five
measured passes produced no recommendation changes; candidate probabilities and
values changed where the corrected clock applies. Baseline median/P95/max were
1.342/28.920/31.035 ms; v3 measured 1.350/31.605/32.570 ms on this machine.
These small-sample results verify regression behavior, not calibration.

## Full one-shanten lookahead (model v4)

Every one-shanten discard, pass, call continuation, and replacement continuation
uses all effective physical draws and legal subsequent tenpai discards. Each
branch reuses exact wait scoring for ron/tsumo yaku, red fives, and river/server
furiten. Branch probabilities multiply their own points before aggregation.
Earlier ineffective own draws retain their probability mass and deplete the
unknown pool without replacement. The draw reaching tenpai cannot also be the
first winning self-draw: only its remaining event suffix can win.

This is complete enumeration of the next effective draw and discard, not a
complete game tree. Earlier ineffective tsumogiri cannot cause branch furiten:
if H+A-X waits on B, swapping A and B proves B was an effective family too.
Future opponent reveals/calls and later ready-hand pool changes remain outside
this lookahead. The follow-up discard risk addition is described below. Two-shanten and farther
positions retain explicitly labelled estimates; future riichi is not assumed.

Expanded search has a cooperative two-second budget and cancellation checks
inside branches and before returning. An expired or cancelled decision returns
no candidates, rather than ranking a mix of search precisions. The worker still
rejects results whose situation key is stale. This is a cooperative boundary,
not a hard real-time deadline inside a scoring-library call.

The final 18-state comparison used one warmup and five measured passes (90
samples per version), with deterministic output across repeats. v3 measured
median/P95/max 1.306/31.666/36.336 ms; v4 measured 26.597/805.532/817.334 ms.
Ordinary-efficiency median was 3.918 ms, broad one-shanten 64.504 ms, ankan
498.111 ms, daiminkan 716.209 ms, shouminkan 520.813 ms, and sanma kita 813.837 ms.
Full replacement search is substantially more expensive; these measurements do
not guarantee a universal latency bound. The corpus changed recommendations in
`broad-one-shanten` and `river-furiten`, without establishing stronger play.

Regressions now cover the direct tsumo-only branches, insufficient time, miss
mass against an independently enumerated urn, coupled point weights, red-tile
accounting, furiten, all-candidate precision, and enumeration-order invariance.
The former strong-kokushi exact-discard assertion was a model-ranking assumption:
the full search can favor a furiten thirteen-sided double-yakuman route. A new
rule test verifies its zero ron/96000-point dealer tsumo values and the ordinary
48000-point alternative; the strong-hand continuation assertion remains.

## Native original-score ledger

Candidates now include `scoreBreakdown`: signed original win income, base
deal-in losses, risk-preference adjustment, efficiency and late-tenpai rewards,
riichi cost, and applicable action penalties. Zero terms are omitted.
`roundingAdjustment` explicitly reconciles original intermediate/final rounding,
including rounded child scores in replacement averages. These diagnostic terms
sum to the score already used for ranking; they never drive a new score.
The report exposes this ledger separately as `nativeScoreBreakdowns`, retaining
the legacy derived `scoreComponents` and its residual for older versions.

The native-ledger change preserved all existing advice fields and candidate
order after stripping only the new ledger and runtime: all 18 fixed states and
131 published candidates matched the pre-ledger source. All ledgers reconciled
to their scores. Special tests also cover fourth riichi, fourth kan, immediate
replacement wins, no-yaku calls, and abort normalization. The 102-test advisor
suite passed, alongside the existing Node, formatter/logging, and offline
WebKit components. This completes the original-score decomposition part of
step 4; it does not replace the score with terminal-outcome expected returns.

## Remaining validation prerequisites

The original-score ledger is the first part of step 4. Replacing it with a
complete terminal-return model remains pending: competition does not separate
opponent self-draw and discards between opponents or assign their payments.
New riichi declarations now share survival across own wins and forced deal-ins,
but their residual competition still has no payment model, and exhaustive-draw
settlement needs the joint tenpai distribution. Adding independent estimates
together would not
produce mutually exclusive terminal probabilities. Existing deposits are already
in winning scores; weighted deal-in losses already include their probability.
Neither should be charged or credited a second time.

The repository's recorded replay contains 60 frames and 48 actions (steps
63–110), with no opening or terminal event. Its tests explicitly retain
`handComplete=false` and `historyComplete=false`; 16 of its 22 draws hide the
tile. `turn.json` is a separate opening snapshot, and the evaluation corpus is
primarily synthetic. The terminal decoder currently retains final scores and
end flags, not full winner/payer, ron/tsumo, payment, tenpai, or draw-reason labels.
This is useful regression evidence but not a calibration dataset.

Step 5 risk features, ippatsu/ura and kan-dora estimates, and second-level
optional actions need separate rule definitions and independent comparisons.
No new coefficients or accuracy claims are introduced without evidence. Before
using discard style or river-pattern features, verify complete histories and
feature availability at the decision time. The protocol's `moqie` and riichi
step fields alone do not establish that dataset coverage.

Step 6 rule, stability, stale-result, and runtime checks run locally now.
Probability accuracy remains unverified until complete, trustworthy outcome
labels and match/time-separated evaluation sets exist. Long-run decision return
also remains unverified until a rule-consistent simulator, explicit continuation
policies, paired initial conditions, and varied opponents are available. A real
continuation after action A cannot be reused as the outcome of proposed action B.

## Meld scoring order regression (model v5)

Rule review found that the scorer expects a chi's lowest tile first, while a
called low tile is naturally appended after the consumed tiles. A valid
`[2s, 3s, 1s]` meld could therefore be rejected as a nonwinning hand. Sort a copy
of each meld's physical IDs at the scoring boundary, retaining original
allocation order for red-tile accounting and leaving the public snapshot intact.

The focused regression changes a valid white-dragon self-draw from zero to
1500 points. Permutations of red chi, pon, open/closed kan, and an implicitly
encoded normal-five kan retain consistent scores and physical identities.
`chi-called-low-yakuhai` extends the corpus to 19 cases; its called-low chi now
receives its legal value. This is a rule correction, not a calibrated risk change.

Final verification passed 104 advisor-related tests, 31 Node tests, 6
formatting/logging tests, and both offline WebKit suites. Comparing the original
`59a30d5` source with the final working source across 19 cases, one warmup and
five measured passes (95 samples each), produced deterministic repeated outputs.
Baseline median/P95/max were 1.402/31.241/33.073 ms; final v5 measured
21.104/808.405/819.043 ms. Recommendations changed for `broad-one-shanten`,
`river-furiten`, and `chi-called-low-yakuhai`. The added case changes the workload
mix, so compare the two sides of this run rather than aggregate percentiles
across different corpora. The wider search is more expensive, and none of these
results establishes improved real-game returns.

The initial local smoke comparison on 2026-10-04 used source `59a30d5`, all 18
cases, one warmup pass, and five measured passes (90 samples per version).
Both identical source versions produced the same candidates and recommendations.
Baseline median/P95/maximum were 1.252/28.194/29.751 ms; the working-source copy
measured 1.308/28.108/29.386 ms. These are a small warmed sample on one machine,
not a performance guarantee. A separate comparison against pre-fix commit
`33afbb4` detected the changed `new-riichi-changed-waits` recommendation, confirming
the report also captures a real historical behavior change.

## Riichi forced-discard absorption (model v5-riichi-risk)

New riichi declarations now evaluate future wins and forced-discard deal-ins in
one event recurrence. At an own draw, winning tiles and discarded tiles are
disjoint branches: the live mass credits its win income and probability-weighted
forced-discard payment once, then removes both terminal probabilities before
continuing. Enemy discards can produce ron before the next own draw. The new
`futureForcedDealInProbability` and existing loss both include survival of the
declaration discard, so neither represents an independent extra first-discard
hazard. Riichi replaces its earlier unlocked win income with the joint income;
the deposit calculation uses the resulting win probability.

The existing competition coefficient is unchanged. Within this recurrence it
is explicitly a conditional residual hazard for other endings, applied once
after own wins and forced deal-ins. It is not another estimate of the same
forced-discard event. This defines consistent model accounting, not evidence
that these uncalibrated rates correctly separate real opponents' outcomes. The
unknown pool, public opponent features, `.45` ron factor, and point estimates
remain frozen. Reusing the same own-draw hit rate is still a with-replacement
approximation; later public reveals and safe-tile changes are not simulated.
Each forced-discard danger assessment does remove its just-drawn physical tile
from the unknown counts; later draws still reuse those frozen conditional rates.
This change applies only to new-riichi evaluation, not every later locked action.
Shape and late-tenpai rewards remain heuristic score terms, not terminal payments.
The former separate 12-draw risk cutoff is removed so both future wins and
losses use the same existing bounded opportunity horizon (at most 24 own draws).
Four-player fourth-riichi aborts still have no future wins or forced discards.

The two-draw mathematical probe with a 10% forced deal-in rate and 8000-point
payment now produces `8000 * (1 - .9 ** 2) = 1520`, replacing the old 1600.
Additional regressions cover empty horizons/pools, zero risk, certain deal-in,
declaration survival, winning draws never being discarded, a later ron being
excluded after a terminal loss, coupled ron/tsumo point weights, residual
competition mass, and the common horizon past twelve draws. With a 20% self-draw
win rate and 10% danger on nonwinning tiles, two own draws give win probability
`.2 + .72 * .2 = .344` and forced-deal-in probability `.08 + .72 * .08 = .1376`;
the remaining `.72 ** 2` completes the unit probability mass.

All 115 advisor, worker, and benchmark tests passed. The 19-state comparison
against `b658903` used one warmup and five measured passes (95 samples per
version), with deterministic repeat outputs. Baseline median/P95/max were
20.837/789.142/832.036 ms; the working variant measured
21.094/815.869/825.643 ms. This was a shared-machine measurement, not an isolated
speed comparison. Only `new-riichi-changed-waits` changed recommendation, from
riichi on `7m` to discard `9m`. Its `7m` riichi still clears old discard furiten
and retains legal ron, but now accounts for future loss suppressing later wins.
The old assertion that this legal candidate must rank first was replaced with
the actual rule contract. These results validate accounting and regressions;
they do not establish calibrated probabilities or improved real-game returns.
The complete local report is `build/advisor-riichi-risk-comparison.json`.

A follow-up count regression verifies that drawing the last unknown honor makes
it safe against an open opponent: the drawn tile cannot remain in that opponent's
hand. The added regression fails before conditioning on the physical draw, and
all 116 advisor-related tests pass after the correction. The timing comparison
above predates this follow-up count correction.

## Decision-local exact scoring cache

Repeated complete-hand scores now share a cache within one `advise` call. The
key retains concealed/winning red identity, meld tiles and types, ron/tsumo,
seat and player count, riichi/double riichi, replacement-win status, seat/round
winds, honba, deposits, North extractions, dora indicators, and every configured
optional scoring rule. It does not approximate or merge scoring inputs. Returned
score dictionaries and yaku lists remain independent. The cache is released in
`finally` on success, cancellation, budget expiry, or an unexpected exception;
hits still check the cooperative search boundary. The model stays v5, and the
two-second production budget and snapshot-key rejection remain intact.

All 109 advisor/worker/benchmark tests passed, including full output equality
between cached and uncached scoring for all 19 fixtures after removing only
`elapsedMs`, individual scoring-key dependencies, cache lifetime, mutable-result
isolation, cancellation, and budget checks. An independent source review found
no blocking issue. No deep-copy or model changes are part of this optimization.

The 2026-10-04 comparison against `b658903` measured these local latencies:

| Protocol | Samples per version | Baseline median/P95/max (ms) | Cached median/P95/max (ms) |
| --- | --- | --- | --- |
| One excluded warmup pass, five measured passes | 95 | 21.209 / 812.027 / 836.572 | 20.904 / 644.154 / 660.915 |
| Fresh interpreter for every case, three repetitions | 57 | 34.332 / 782.109 / 799.420 | 33.450 / 614.041 / 623.720 |

Both series preserved every candidate field and recommendation, with consistent
repeated outputs. The warm series used `scripts/advisor_compare.py --baseline
b658903 --warmups 1 --repeats 5`; the cold series called its
`run_version(source, [case], warmups=0, repeats=1)` in a fresh worker for every
case and repetition. Imports and process startup remain outside measured time.
Timing runs were serialized with the other development tests. Baseline ran
before cached source in each series, so load and run order still limit causal
latency claims; the smaller cold tail is not evidence that cold calls are
intrinsically faster. These are samples from one machine, not a universal bound.

A separate allocation probe warmed the whole corpus, then ran one measured pass
with `tracemalloc.start(1)` and garbage collection before each case. Its diagnostic
process alone extended the search deadline to 120 seconds to accommodate tracing;
none of those instrumented times enters the latency table. Maximum per-decision
traced Python allocation was 6.153 MiB at baseline and 11.932 MiB with caching,
both on `sanma-kita`. This includes structural-cache allocations and scorer
temporaries, not total process RSS. The scoring ContextVar was empty after every
call. In that case 7908 scoring requests became 3996 actual scorer calls; the
`ankan` fixture went from 4103 requests to 1599 scorer calls. These fixture counts
are not the previously sampled, different concealed-kan hand and do not imply
the same factor of end-to-end speedup.

The ignored `build/scoring-cache-warm.json`, `build/scoring-cache-cold.json`, and
`build/scoring-cache-memory-{baseline,current}.json` retain local samples and
allocation evidence. The optimization trades temporary decision memory for fewer
scorer calls; it establishes output equivalence on these regressions, not better
win rates or calibrated probabilities.

## Conditional one-shanten follow-up risk (v5-lookahead-risk)

The previous continuation policy maximized gross winning income. In the
`2345667m34568p44s` regression, discard `8p` and draw `4s` against seat 1's
riichi with safe `3p`. With twelve events left, that policy chose `6m` for
563.52 gross income despite 530.40 expected immediate loss; `3p` offered 243.52
gross income and 10.40 expected loss. The expanded real decision window already
preferred `3p`. Future legal tenpai discards now reuse the present-position score,
including risk weight, efficiency, late-tenpai reward, rounding and tie order.
All three ready-discard scores agree with the expanded window: `3p` 1510.8,
`6m` 1180.3, and `6p` 888.6. No heuristic coefficients were fitted or changed.

Each effective-draw arrival has a conditional follow-up deal-in probability
`q`, expected payment `L`, and surviving ready-hand win probability/value
`p`/`V`. For arrival weight `a`, it contributes `a*q` to the modeled follow-up
deal-in terminal, `a*L` to loss, and `a*(1-q)*p` / `a*(1-q)*p*V` to winning
probability/income. The current discard's survival multiplies both future
metrics once. Thus a follow-up deal-in cannot also earn subsequent win income,
and a final effective draw still incurs its discard risk with no winning suffix.
The original competition factor remains in `a`, before the follow-up decision,
as in the prior effective-arrival model. It is an uncalibrated residual survival
estimate, not another explicit follow-up payment. This preserves its historical
placement; it does not unify event ordering across all advisor submodels.

`futureDiscardDealInProbability` and `futureDiscardDealInLoss` expose the
unconditional weighted future event separately from the current discard. The
native ledger and comparison runner retain the separate loss, including
replacement-draw weighting and abort normalization. Shape and late-tenpai
rewards retain their heuristic meanings; the score is not full terminal EV.
Only the first effective draw's legal tenpai discards are compared. Folding
back out of tenpai, earlier ineffective tsumogiri danger, unknown opponent
reveals, and later pool changes remain outside this bounded search.

Regressions cover the expanded-window mismatch, zero/certain risk, terminal
mass conservation, no suffix, competition and first-arrival miss weights,
current-discard survival, replacement robbery survival, and preservation of
future loss during abort normalization. The added
`one-shanten-followup-risk` fixture extends this branch's corpus to 20 states.

All 110 advisor, worker and benchmark tests passed. The offline comparison
against merged v5 source `b658903` used one warmup and five measured passes
(100 samples per version), with deterministic output across repeats and no
availability changes. Baseline median/P95/max were 23.099/691.176/781.489 ms;
the follow-up-risk model measured 26.308/771.446/856.035 ms. Only
`river-furiten` changed its root recommendation. The added regression retains
its root recommendation while correcting the modeled `4s` continuation.
This warmed sample shows additional computation cost; it does not establish
better game returns, calibrated probabilities, or a universal latency bound.
The full report is `build/advisor-lookahead-risk-comparison.json` (ignored).

## Deterministic risk-rule boundaries (v5-risk-rules)

An exhausted `1m` or `9m` in sanma cannot complete a sequence, pair, or triplet.
It now has zero danger against an opponent with a meld, including a concealed
kan. A meldless opponent retains the existing small missing-singleton kokushi
estimate. The reproduced `1m` case changes from probability 0.008775 and loss
8.775 to zero. Four-player terminals, other exhausted suited tiles, and all
non-exhausted sanma-terminal rates keep their prior heuristic treatment. This
is a legal-shape exclusion, not a new fitted danger table.

Public melds now establish single-ron payment lower bounds for Daisangen,
double Daisuushii, and Suukantsu, stacking the independently confirmed units.
The repository's [rule reference](%E9%9B%80%E9%AD%82%E8%A7%84%E5%88%99_Agent%E5%8F%82%E8%80%83.md#63-%E5%8C%85%E7%89%8C%E8%B4%A3%E4%BB%BB%E6%94%AF%E4%BB%98)
documents responsibility for the first two, not four kans. The last relevant
meld and its public `froms` identify the responsible feeder; extending a pon to
a kan preserves that original source/order in the decoder. A final concealed
kan has no feeder. A known different responsible player halves only the liable
yakuman component; our own responsibility pays it in full. Existing deposits
are excluded. For the supplied nondealer Daisangen example the prior 3900
estimate becomes 32000 if we are responsible, 16000 if another player is
responsible, or a 16000–32000 interval when old snapshots lack the source.

The `yakumanPayment` diagnostic retains the confirmed yaku and lower/upper
bounds; the danger estimate uses its lower bound. For shared or unknown
responsibility, the current snapshot/rule contract does not settle the honba
allocation, so bounds include zero through the full honba instead of inventing
an exact payer. Additional hidden yakuman, multi-ron honba priority, and our pao
payments when another player deals in or the opponent self-draws remain outside
this immediate-discard model. These are payment floors, not complete opponent
hand valuations or a complete responsibility-payment simulator.

Discarding a red five now adds one known han to the same ordinary opponent
estimate through the existing scorer. It preserves the tile-family probability
and naturally respects mangan and higher caps: the riichi probe changes from
5200/5200 for normal/red to 5200/8000. Both true and counted yakuman remain
unchanged by the extra red han. No unknown concealed bonuses or coefficients
were added. Focused tests cover both sanma terminals, closed kokushi, four-player
and ordinary-suit boundaries, payer uncertainty, dealer/sanma honba, source
retention through added kan, compound yakuman, red caps, genbutsu, and input
immutability.

All 116 advisor, worker, and benchmark tests pass. The 19-state comparison with
merged v5 `b658903` used one warmup and five measured passes (95 samples each).
Baseline median/P95/max were 20.749/772.281/785.279 ms; this rule variant measured
20.501/780.264/801.021 ms. No root recommendations changed in that existing
corpus. The supplied counterexamples are separately asserted by the focused
rule tests; the corpus is not a representative sample of these rare shapes.
The full report is `build/advisor-risk-rules-comparison.json` (ignored).
Timing is local regression evidence, not a universal latency bound or evidence
of improved real-game returns.

## Cross-PR integration verification

A local assembly of PR #14 (`f85faf1`), PR #11 (`e0907d8` plus `eee0f59`),
PR #13 (`bb5045b`), and PR #12 (`087aec9`) was checked together. The assembly
resolves only model-label and appended-document conflicts; its local source
commit is `215f04c`. These PRs remain independent changes based on merged v5;
this check does not merge them or replace their individual comparisons.

The combined source passes 139 advisor/worker/benchmark tests, 31 JavaScript
tests, and 6 formatter/logging tests. An additional conditional-draw probe
confirms zero forced-deal-in risk for the last sanma `1m` and `9m` against an
open opponent. Cached/uncached complete-output equivalence also passes with all
model changes and the added twentieth fixture.

The final 20-state comparison against `b658903` uses one warmup and five
measured passes (100 samples per version). Baseline median/P95/max are
22.985/697.071/805.561 ms; the assembly measures 25.713/609.752/709.473 ms.
Every repeated output is deterministic. Only `river-furiten` and
`new-riichi-changed-waits` change root recommendation. The report remains a
regression/performance measurement, not evidence of stronger play or calibrated
risk. Full local evidence is `build/advisor-batch-comparison.json` in the
integration worktree.

Both offline native WebKit checks remain **unverified in this session**. The
replay test receives no script messages, and the overlay test returns
`WKErrorDomain Code=5` for JavaScript evaluation. Sandbox-extension denials are
also logged. Running the same two checks on an unchanged `b658903` source
archive reproduces both failures. No permissions were expanded, no game login
or live game connection was used, and these checks are not counted as passed.
The ordinary Python/JavaScript checks above do not substitute for a native
WebKit pass. Local diagnostics are in `build/native-tests.log`,
`build/overlay-tests.log`, and their `*-baseline-tests.log` counterparts.

## Passed current-discard evidence in one-shanten continuations

Reaching a future own draw proves that the current public discard and any
modeled root discard have passed. One-shanten branches now supply that evidence
to the shared opponent-risk builder. The current river event is safe only for
opponents whose recorded riichi precedes it; an explicitly survived root discard
is safe for already locked opponents. Red and ordinary fives share the same safe
tile family. Non-riichi opponents retain their modeled risk. Current-window
danger keeps the strict event boundary, and neither the snapshot nor its event
clock is changed. No unknown intervening discard is invented.

The `passed-current-discard` fixture skips seat 3's `5p` after seat 1's riichi.
Its draw-`1z`, discard-`5p` continuation previously retained 10.36% deal-in risk
and 525.2 expected payment; the explicitly expanded next-draw window gave 0.4%
and 5.2. The additional 520 came from the already locked seat. The corrected
branch also propagates the resulting suji evidence for its alternative `2p`
discard. Regression checks compare all legal ready discards, chosen follow-up,
probabilities and scores with the same unknown pool and remaining event suffix.
This repairs state consistency and does not establish stronger play.

## Confirmed-riichi continuation absorption

Confirmed riichi now enters the same joint win/forced-discard recurrence from
the common position evaluator. Ordinary tsumogiri, skipping a server-offered
legal ankan or North extraction, and nonwinning replacement children therefore
absorb wins and deal-ins before later events. Waiting analysis supplies its
actual event order, including a final own draw or a pending enemy discard.
The current discard uses its unrounded danger once; its expected loss remains
separate from future forced losses. Already-paid riichi sticks are never charged
again. New declarations alone add the existing deposit calculation and retain
the fourth-riichi abort reset.

Future forced discards reuse the passed-discard safety evidence above: the
survived root discard or current public discard is safe against the relevant
riichi opponents, while the current discard risk and non-riichi risks remain.
No hypothetical intervening opponent actions are inserted into the snapshot.

Replacement decisions average future forced probability/loss from their children
and apply robbery survival once, alongside the existing child score ledger.
Immediate replacement wins and fourth-kan aborts have no subsequent forced
discard losses. The three new confirmed-riichi fixtures use an ordinary locked
discard, a just-drawn fourth triplet tile that can legally be concealed-kanned,
and a drawn North in sanma. These are consistency regressions with real optional
choices, not evidence of stronger play or calibrated probabilities. The frozen
unknown-pool approximation, risk coefficients, competition model, two-second
budget, cancellation, and decision-scoped scoring cache remain in place.

## State-consistency verification (2026-10-04)

The latest main is `df7293e` (README-only PR #15 after `ffc3030`). The two
changes are stacked: passed-discard evidence at `3d18085`, then confirmed-riichi
absorption at `c91fa11`. Rebasing onto the README update changed none of their
source, tests, scripts, or evaluation documentation. Source hashes and every
non-runtime output in the subsequent latest-main comparison match the original
comparison. The independent final source review found no blocking issue.

The unchanged baseline passed 141 advisor/worker/benchmark tests; the first
change passed 144; the combined source passed 151. Each version also passed
31 JavaScript and 6 formatting/logging tests. The new regressions were run
against the old source first: passed-discard checks failed in 11 subcases,
and the confirmed-riichi checks exposed missing fields and excessive win mass.
These checks include cancellation, budget expiry, stale-worker suppression,
cached/uncached equivalence, score reconciliation, physical counts, immutable
snapshots, and mutually exclusive terminal probability bounds.

All comparisons used the same 24-case corpus (the original 20 plus one
passed-discard and three confirmed-riichi cases), one excluded warmup pass,
and five measured passes: 120 observations per version. The shared fixture
SHA-256 is `188161c7c7db6a2fe1f6d34b4e699ea84826f67331fadd55e7fc78e6051fe4f7`.
Both sides were deterministic in every run, with no availability or root
recommendation changes. Timing runs were serialized after test completion.

| Comparison | Baseline median/P95/max (ms) | Changed median/P95/max (ms) |
| --- | --- | --- |
| Original main source to passed-discard evidence | 22.437 / 653.038 / 763.067 | 22.860 / 637.688 / 754.639 |
| Passed-discard evidence to confirmed-riichi absorption | 22.671 / 633.595 / 755.356 | 22.222 / 639.224 / 758.546 |
| Latest main `df7293e` to combined `c91fa11` | 20.730 / 598.771 / 689.759 | 21.616 / 601.516 / 700.827 |

The first change affects only the pass candidate's score in its new fixture:
419.5 becomes 495.7, while pass remains preferred. The second changes scores in
five cases: new-riichi changed waits, confirmed-riichi furiten, ordinary locked
discard, legal ankan, and legal North extraction. Existing choices remain
preferred. The new declaration's small score change reflects use of unrounded
current danger; no coefficients were changed. For the original ordinary-discard
reproduction with no existing pot, win probability becomes 30.09% from 33.85%,
and future forced loss is now included. The exact result also accounts for the
root tile becoming safe against the riichi opponent after surviving its current
discard. This is accounting consistency, not evidence of calibrated probability
or stronger play. These warmed local timings do not establish a latency bound
or a speed improvement; version order and machine load remain confounders.

Full reports are retained under ignored `build/` as
`passed-discard-comparison.json`, `confirmed-riichi-incremental-comparison.json`,
and `confirmed-riichi-latest-main-comparison.json`. Reports contain their full
input corpus, source hashes, every candidate field, and individual timings.
Reproduce the final comparison with `scripts/advisor_compare.py --baseline
df7293e --current-ref c91fa11 --warmups 1 --repeats 5 --output
build/confirmed-riichi-latest-main-comparison.json` using the existing Python
environment. The first two runs used the pre-rebase commits with identical
source hashes and the same combined fixture file.

Both native WebKit suites remain unverified: the replay receives no script
messages and the overlay fails with `WKErrorDomain Code=5`. The unchanged
baseline and both changed versions reproduce these failures in this sandbox;
baseline logs also contain sandbox-extension failures. They are not counted
as passes. No permission was expanded and no game session was opened.

Deferred work remains separate: temporary furiten clearing on normal draws;
haitei/houtei/chankan event yaku; repeated terminal loss in nine-terminals abort
comparisons; multi-ron honba allocation; a complete terminal net-EV ledger;
without-replacement winning draws; same-shanten red-tile exchanges; two-shanten
search; and a complete terminal-outcome dataset. None is implemented here.

## Current: finite continuation and concrete yaku routes (v9, 2026-10-05)

The model is `public-information-actions-ev-v9-finite-routes`. The comparison
baseline is v8 at `69c693f250ba13eeded39ae2b0780b4b8b0dd66d`. Earlier sections
retain their historical measurements and limitations; the method in this
section describes v9. Final integrated measurements are recorded below only
after the implementation and required checks have stabilized.

### What is evaluated

`advisor_continuation.py` gives ordinary non-ready candidates a common explicit
own-draw/discard frontier. It samples each physically available draw, including
red fives, and compares every resulting discard. A draw that preserves shanten
can now improve the continuation's monetary estimate, instead of influencing
only a tie-break. The first draw depletes the public unseen pool. Structural
ukeire is no longer capped at 32. Immediate ready positions still use scored
waits; the farther ordinary tail remains an approximation with projected
progress, future waits, retained value and frozen public risk. This is one
explicit draw followed by a tail, not an exact two-draw game simulation.

Replacement actions spend that same explicit unknown draw on the replacement
tile. Their resulting discard candidates use the common leaf contract rather
than receiving an additional ordinary-draw search depth. All root actions must
finish before a result is published. Cancellation and the cooperative two-second
budget still discard an incomplete decision rather than expose a partial rank.

`advisor_routes.py` supplies physically feasible completed-hand targets for
open yakuhai and toitoi routes. The targets retain fixed melds, require missing
copies to exist in the unseen pool, and score the completed shape with real
dora and physically available red-five alternatives. The search retains nearest
targets per value honor or pair, not every possible winning hand. After the
explicit draw, the policy can select a suitable target and a paid surplus
discard. It does not add the probabilities of overlapping target routes.

Each selected target uses a without-replacement collection model for its own
missing tiles. Non-winning draws pay future discard risk; competing opponent
endings and exhaustive-draw settlement remain in the same mutually exclusive
ledger. These target routes claim tsumo only, avoiding speculative ron income
when intermediate discards and resulting furiten are not tracked. Ordinary
closed projections also do not receive free future riichi. Riichi remains an
explicit server-offered action with its deposit and forced-discard costs.
The unidentified open-yaku 0.3 income prior has been removed. Concrete scored
waits determine ready-hand yaku status, including a call that completes a valid
toitoi wait; such a call no longer inherits a false 500-point no-yaku penalty.

Kokushi keeps its explicit missing-orphans/pair progression rather than borrowing
ordinary-hand progress. Root one-shanten kokushi retains exact improving branches
and scored waits, including the thirteen-sided double-yakuman distinction;
two-shanten and farther frontier leaves retain projected payments. A dominant
seven-pairs leaf compares actual targets with
seven distinct pairs; four copies cannot supply two pairs. The bounded seven-pairs
target set retains held pairs and pairs existing singletons, omitting routes that
would collect two copies of an absent family. These special-hand models do not
establish complete optimal search across every possible route.

### Defensive continuation and explanations

The current defensive first discard must still minimize current expected loss.
After a held tile survives, later held copies become safe against already-locked
riichi opponents; other opponents keep their own risk. The defense also tracks
the initially known safe/unsafe class of future draws without replacement.
Drawing and discarding a safe tile preserves held stock. It does not invent a
future opponent discard or add safe tiles beyond the physical pool. A suffix
entered after unspecified previous misses depletes safe supply conservatively.

A defensive hand that is already structurally ready can retain exhaustive-draw
tenpai income only on branches that never spend its held stock. Spending stock
forfeits that income. The defense still claims zero self-win income and does
not combine attack receipts with a cost-free retreat. Conditional post-draw
entries distinguish a known safe draw from a known unsafe one, so turning down
an unsafe draw cannot grant a second chance to sample a safe tile in that turn.

Candidate diagnostics distinguish structural ukeire, finite-draw improvement,
concrete yaku routes, current/future risk, strategy choice and the signed terminal
ledger. Recommendation reasons identify the principal modeled advantage over
the next candidate and flag small advantages. These explanations describe the
model comparison; a positive score gap is not proof of a stronger real discard.

### Fixtures and reproducible comparison

The repository adds eleven targeted public snapshots in
`tests/fixtures/advisor_route_cases.json`: 1329, 297, 561, 640, 590, 572,
658, 659, 663, 664 and 1007. They retain the decision inputs needed to reproduce
the calculation, without player identities, transport credentials, session
metadata, hidden hands, complete logs or later outcomes. In particular, 590
checks the real value of an honor route despite lower structural ukeire, and
1007 checks a valid early genbutsu discard. They prevent an unconditional
honor-discard rule from masquerading as the requested correction.

The 57 existing fixtures plus these eleven form a shareable 68-case corpus.
The separately frozen local log contains 142 windows whose recorded v8 best
action is an ordinary discard. Its full set of executable discard windows has
156 entries, including nine recorded kita choices and five riichi choices.
The 142-window selection depends only on the contemporaneous advice, never on
the later hand result. Complete local log exports remain outside Git.

```sh
.venv/bin/python scripts/advisor_log_fixtures.py \
  --fixtures tests/fixtures/advisor_cases.json \
  --fixtures tests/fixtures/advisor_threat_cases.json \
  --fixtures tests/fixtures/advisor_phase_cases.json \
  --fixtures tests/fixtures/advisor_policy_logged_cases.json \
  --fixtures tests/fixtures/advisor_route_cases.json \
  --output /tmp/maj-soul-v9-public-cases.json
.venv/bin/python scripts/advisor_compare.py \
  --baseline 69c693f250ba13eeded39ae2b0780b4b8b0dd66d \
  --fixtures /tmp/maj-soul-v9-public-cases.json \
  --warmups 1 --repeats 3 --include-internal \
  --output /tmp/maj-soul-v9-public-comparison.json
```

Use the existing Python environment if its executable is outside `.venv`.
To add the local log, pass `--log /path/to/frozen.jsonl` to the exporter with
the same five fixture arguments; that creates the 210-case comparison corpus.
Add `--all-discard-windows` to include the fourteen optional-action windows as
well. The exporter allowlists nested public fields and does not copy arbitrary
log metadata into fixtures.

The runner snapshots both source trees before execution, checks the imported
advisor path, and runs each version in an isolated `-I -B` interpreter. Reports
record source hashes, environment, every root candidate, native signed accounts,
derived rounded-field residuals, repeat consistency and individual latency
samples. `--include-internal` also records first-pass unrounded candidate fields,
including the named `Outcome` account. It is an offline diagnostic option, not
a change to the application output. Measured budget expiries count as timeouts
and remain in latency statistics; unexpected non-timeout availability failures
still stop the comparison. Warmup passes are excluded from reported timings.

### Integrated results and remaining limits

The final serial comparison used Python 3.12.15, `mahjong` 2.0.0 and
macOS 27.0.1 arm64. Each version received one complete warmup pass and three
measured passes over the same 210-case corpus. Both versions had **zero measured
timeouts in 630 calls**, zero warmup timeouts in 210 calls, no unexpected status
changes, and identical repeated outputs after excluding elapsed time.

| Corpus | Calls per version | v8 median / P95 / max (ms) | v9 median / P95 / max (ms) |
| --- | ---: | ---: | ---: |
| All 210 cases | 630 | 44.86 / 322.78 / 1104.94 | 513.33 / 1198.12 / 1823.07 |
| 142 recorded discard windows | 426 | 54.68 / 269.89 / 441.34 | 527.76 / 1049.90 / 1313.91 |
| 57 existing fixtures | 171 | 43.36 / 787.19 / 1104.94 | 409.71 / 1765.72 / 1823.07 |
| 11 targeted snapshots | 33 | 16.00 / 458.85 / 458.97 | 395.44 / 1291.43 / 1316.88 |

The richer search is substantially slower. These measurements establish that
this corpus completed within the unchanged two-second budget on this host;
they do not guarantee every future live state will finish in time. An expired
or cancelled search still publishes no partial candidate ordering.

The fourteen additional executable discard windows whose recorded recommendation
was kita or riichi also completed one warmup and three measured passes with
zero timeouts, stable output and no ledger violations. Their 42 measured calls
have median / P95 / maximum 351.98 / 1148.94 / 1166.46 ms in v8 and
727.43 / 1194.09 / 1240.77 ms in v9. One recommendation changes, at serial 581,
from kita `4z` to discard `5z`. These supplement the 142 ordinary-discard windows
above.

Three fresh-process first calls were also measured for each heavy public case,
without warmup and excluding interpreter/module startup. All nine completed
with unchanged budget and the same source fingerprint:

| Case | Cold median / maximum (ms) | Timeouts |
| --- | ---: | ---: |
| `pon-red-choices` | 1702.76 / 1713.94 | 0/3 |
| `daiminkan` | 861.40 / 861.82 | 0/3 |
| `shouminkan-red` | 1848.66 / 1854.09 | 0/3 |

The heaviest observed cold case leaves limited headroom below two seconds.

Source SHA-256 fingerprints, computed over the isolated `src` trees:

- v8: `3bcf214a2efa35b80ab662b2f09478048d9ad1467162915b8508cc4a23398f27`
- v9: `a79af7dd8a86d215311d5aa91aa475252aa603df53ee441221e93f8797123378`
- Local 210-case corpus: `ae336196e3c6b4a06deaa2742558b8d455e365c326ad9867e98f15c673babf99`

Every version's first measured pass retains 2,184 root candidates and 201
replacement children. The 2,379 candidates carrying a terminal `Outcome` ledger
pass the independent probability
and account checks; six existing abort-action candidates use their separate
accounting contract. The largest v9 terminal-mass error is `2.6e-15`, signed
display-account error `4.6e-13`, and internal account error `1.9e-12`.
The score's explicit rounding adjustment stays within 0.05 points. No candidate
is selected using rounded display fields.

There are 38 changed recommendations in the 142 recorded discard windows,
eight in the existing fixtures and five in the targeted snapshots. The latter
sets overlap some recorded situations and are not independent evidence.
Recorded-window current strategies change from 130 attack / 12 fold to
125 attack / 17 fold. These are descriptive counts, not a target fold rate or
evidence that a changed recommendation improves actual results.

| Recorded serial | v8 recommendation | v9 recommendation | Checked interpretation |
| --- | --- | --- | --- |
| 1329 | discard `7p` | discard `1z` | 44 versus 35 effective unseen tiles no longer share a 32-tile cap; continuation income reflects the preserved shape. |
| 297 | discard `5p` | discard `1z` | The selected candidate has 16 rather than 17 immediate effective tiles; actual same-shanten first-draw improvements affect its continuation. |
| 561 | discard `3p` | discard `1z` | Keeping the two-shanten route beats retreating to three shanten under the common continuation. |
| 640 | discard `7s` | discard `1z` | The old `7s` line received 313.494 points of win income from unidentified open yaku. Its v9 chosen policy receives zero; structural draw settlement remains legal. |
| 590 | discard `5p` | discard `5p` | Two retained value honors support separate draw-conditioned yakuhai targets. Lower ukeire is not automatically worse. |
| 572 | pon `2p`, discard `7z` | pass | The first call no longer obtains the unidentified-yaku prior; its explicit tsumo-only route competes with the closed pass. |
| 658 / 659 | pon `7s`, discard `5s` / discard `5s` | unchanged | Call and subsequent discard both evaluate to 62.441 points with the same underlying terms. |
| 663 / 664 | pon `1s`, discard `4s` / discard `4s` | unchanged | Both now evaluate to 2694.112 points; the false call-only 500-point no-yaku penalty is gone. |
| 1007 | discard `7s`, attack | discard `7s`, fold | `7s` is genbutsu against seat 0's riichi, while seat 2 still contributes 0.0112 current ron probability. |

The 590 comparison is deliberately close: discarding `5p` has ukeire 33 and
explicit target win income 36.116, versus ukeire 45 and income 18.058 after
discarding `1z`. Its score advantage is only 2.222 points (49.797 versus 47.575),
and is displayed as a small modeled advantage. For 640 the selected `1z` line
scores -421.388 versus -582.654 for `7s`; both chosen policies have zero win
income, and the difference comes from risk and structural draw settlement.
This is not a proof that discarding a particular honor is globally optimal.

The complete private comparison and candidate-account exports remain local.
The eleven committed snapshots, source fingerprints and reproduction commands
allow the public regression cases to be independently replayed.

The final source passes **352 advisor/worker/benchmark tests** in 195.687 seconds,
32 Node protocol tests and six Python formatting/logging tests. The integrated
script completes these checks before reaching the environment-limited native
test. New regressions cover the logged route boundaries, concrete target urns,
safe-draw defense and conditional retreat, actual special-hand requirements,
cache equivalence and cancellation, root kokushi thirteen-sided payment, and
surplus-discard selection using surviving continuation value. The uncached
arithmetic reference runs directly outside the public deadline; the cached
public calculation must still finish under the unchanged production budget.
`git diff --check` passes.

Native WebKit and overlay checks were attempted separately: the native test
received no protocol packets before its assertion, while the overlay encountered
`WKErrorDomain Code=5`; both emitted denied sandbox-extension diagnostics.
Native UI remains unverified and is not counted as passing validation.

The finite frontier and concrete targets correct specific approximation
discontinuities, but the remaining ordinary progress/wait/value projection,
frozen discard hazards, opponent ending model and target pruning still affect
candidate order. Only our modeled draws deplete these pools; the search does
not reconstruct the actual wall or opponents' concealed hands. Unknown future
calls, future riichi, full re-entry after folding and general ron-eligible target
continuations are not enumerated. Measured fold rates are descriptive rather
than an acceptance target. Regression checks and offline score changes do not
establish calibrated probabilities, higher long-run win rates or avoidance of
the recorded deal-in.

## One-second inference and recorded pon/kan timeouts (v10, 2026-10-06)

Two recorded sanma reaction windows offering pon and daiminkan exhausted the
two-second search budget and skipped their recommendations. Their minimal public
states are now regression fixtures in `advisor_timeout_cases.json`. The optimized
engine returns all offered choices and preserves the original search coverage,
ranked-match preferences, and two-second interruption budget.

Both benchmark versions include PR #25 (`5aa927b`, expanded sidebar) and PR #26
(`cd3c221`, ranked-match preferences). The performance branch is stacked on #26;
#25 was merged locally into the validation checkout. The workload combines 73
existing cases, 14 rank-policy cases, the two actual timeout cases, and 40 local
public discard snapshots: 129 cases total. Full game logs are not committed.

The main changes reuse exact suit decompositions, passed-tile risk evidence,
equivalent future hands, scoring configurations, and completed-hand scores.
Fixed-target collection now counts without-replacement subsets using integer
polynomial coefficients, then applies the original event hazards. Complete
outcomes also share results across equivalent deficit/stock/payment profiles.
The suit calculator remains tied to the pinned `mahjong==2.0.0` implementation
and has differential reference tests for dependency upgrades.

Triplet tsumo prices share a winning representative only when the decomposition
is unique, or when a complete all-triplet hand with no chi and standard counted
yakuman limits dominates alternative sequence decompositions. Closed hands keep
four-concealed-triplet value; one open group keeps toitoi plus sanankou. Tests
cover pair migration (`11122233344`), chanta/junchan, kans, green yakuman, reds,
three/four players, chi, and alternative counted-yakuman rules. Tanki remains
separately priced. The background worker uses a per-calculation cancellation
event; queue updates and publication still hold the condition lock and reject
superseded results, including resubmissions using the same key.

The final local arm64 / Python 3.12.15 / mahjong 2.0.0 measurements are below.
Times are milliseconds; P95 is nearest rank. A warm pass over all 129 cases is
followed by three measured passes. Every cold sample uses a new interpreter.

| Measurement | Samples | Median | P95 | Maximum | Timeouts |
|---|---:|---:|---:|---:|---:|
| Baseline mixed warm workload | 387 | 483.4 | 1613.8 | 2028.7 | 6 |
| Optimized mixed warm workload | 387 | 283.1 | 730.6 | 982.4 | 0 |
| Optimized fresh process per case | 129 | 275.8 | 654.3 | 858.7 | 0 |
| Optimized actual background worker | 19 | 663.5 | 904.8 | 904.8 | 0 |

| Recorded timeout case | Baseline cold timeouts | Optimized maximum of 3 cold runs | Optimized actual worker |
|---|---:|---:|---:|
| `live-timeout-serial-578` | 3 / 3 | 642.5 | 679.5 |
| `live-timeout-serial-1017` | 3 / 3 | 862.9 | 904.8 |

All 129 optimized cold samples, 387 mixed warm samples, 15 repeated heavy cold
samples, and 19 actual-worker samples were below one second, with zero timeouts.
The worker samples include all 14 rank-policy states and five heavy states;
their timer includes snapshot copying, dispatch and the real cancellation
callback. Timings exclude imports, process startup, and the UI publish timer or
rendering. These are measurements on this machine and corpus, not a universal
wall-clock bound for other hardware, system load, or unseen positions.

All 129 ranked-prefix outputs and all 89 committed cases with full ranking were
compared against the baseline, including unrounded private candidate accounts.
Actions, candidate order, reasons, and all nonnumeric fields agree. The maximum
numerical difference was 1.82e-12, caused by floating-point evaluation order;
the comparator uses absolute tolerance 1e-8 and relative tolerance 1e-12.
Every repeated optimized output was stable. Only the two legacy timeout cases
use a separate 120-second diagnostic reference to obtain complete old outputs;
that reference's duration is excluded from every performance result. Production
and all optimized/ordinary diagnostic runs retain the two-second budget.

The original baseline was measured once, including six measured warm timeouts
and six repeated cold timeouts across the two recorded failures. After a first
optimization missed the warm one-second goal (maximum 1048.4 ms), the final
implementation was retested in full. Unchanged baseline results were reused
after verifying source, workload, Python/platform/library environment and
measurement settings. The final report records original file hashes and marks
this reuse explicitly; the final timings do not claim interleaved version runs.

Validation: **430 advisor/worker/benchmark Python tests**, **6 formatting/logging
Python tests**, **48 protocol/overlay Node tests** on the integration tree, and
**45 Node tests** on the performance branch passed. Native UI, package building,
desktop replacement, and a new online playing session are outside this run.

[Machine-readable results](benchmarks/advisor-inference-20261006.json) include
per-case timings, source and fixture hashes, runner hashes, baseline provenance,
all worker results, and complete-equivalence summaries. To rerun against the
same backend baseline with the current committed corpus (the recorded run used
89 committed cases):

```sh
.venv/bin/python scripts/advisor_inference_benchmark.py \
  --baseline cd3c22199713dc524d6377071d201a06919075cb \
  --legacy-timeout-reference \
  --artifacts build/advisor-inference-verification
```

To reproduce the combined UI source hashes, merge #25 into both source trees in
an independent checkout before benchmarking. `--live` accepts an optional local
public-state fixture export. `--baseline-results` reuses only a matching complete
baseline artifact directory and records that provenance explicitly. The runner
saves both source snapshots, its own scripts, full raw results, inputs and hashes.

## Action latency and repeated leaf inputs (2026-10-07)

This optimization is based on the autoplay branch at
`92e26dfc1a64d832ea64db13216de3025e4374bf`. A recorded discard/North-extraction
window exhausted its 2,000 ms wall budget after 2,000.4 ms. The autoplay fix preserved the
enabled switch after that timeout; it did not make the calculation faster or
retry the same window. Current offline replays of the original calculation
finish in a few hundred milliseconds. The historical log lacks worker CPU and
scheduling measurements, so the cause of the live slowdown remains unconfirmed.

The search still evaluates every offered action at the same depth, with the
same two-second budget. Structural improvements share indices internally and
read the actual remaining counts when summing ukeire; public tile lists remain
fresh and ordered. Future ron and tsumo projections share their shape/yaku/dora
scan, then retain separate payment configurations and menzen-tsumo eligibility.
Each physical first-draw branch also reuses the average future discard risk
for identical opponent safety sets. It does not reuse that average across
different draws or extend decision-local caches across advice calls.

The single worker defers explicitly non-actionable playing snapshots for 100 ms
and coalesces newer updates during that interval. Action windows start without
this delay. Every new state still invalidates the previous state, including a
non-actionable state that closes an older action window. A submitted game input
now sends a keyed invalidation to the native worker immediately. An old key
cannot cancel a newer task; no stale or partly evaluated result is published.

Task diagnostics are separate from the advisor's result and score fields:

| JSONL record/field | Meaning |
|---|---|
| `advisor_timing.queueMs` | Native submission to calculation start, or to cancellation if it never starts. |
| `coalesceMs` | The deliberate display-only delay within `queueMs`; do not add it again. |
| `calculateWallMs`, `calculateCpuMs` | Actual elapsed time and worker-thread CPU time during calculation. |
| `deliveryWaitMs` | Calculation finish to UI retrieval or discard. |
| `cancelToFinishMs` | Cancellation request to calculation finish; null for an unstarted or uncancelled task. |
| `outcome`, `stage` | Delivered/superseded/invalidated/closed and queued/running/completed. `delivered` ends at native retrieval, not at JavaScript execution. |
| `advisor_delivery.publishToAdviceMs` | Browser publication of the current snapshot to the delivery callback, using only the browser clock. |
| `advisor_delivery.operationToAdviceMs` | Original live operation receipt to the callback, when a valid browser receipt timestamp exists. |
| `advisor_delivery.current` | Whether the callback still belongs to the current, open advice window. Old/closed windows have no current-window durations. |

All records join on `adviceKey`. No JavaScript/Python clock subtraction is used.
The UI thread drains a bounded 128-record worker queue even when the computation
was cancelled and no advice was published. Records can be lost during a long UI
stall or immediate shutdown. The native delivery callback passes only the advice
key; the browser computes receipt durations and logs them through the bridge.
Submission/cancellation precedes synchronous turn
logging. Neither these timings nor the optimization prove an App Nap cause or a
universal wall-time bound under system load.

The new committed corpus includes three minimal public snapshots from the slow
sequence (1600, 1643, 1661), without account, game or session identifiers or
transport metadata.
The benchmark defaults to the unchanged two-second budget in both performance
and complete-output diagnostics. Only an explicit `--legacy-timeout-reference`
allows the old 120-second reference for the two earlier timeout fixtures;
baseline reuse checks this setting as well as source, runner, fixture and
environment fingerprints.

```sh
.venv/bin/python scripts/advisor_inference_benchmark.py \
  --baseline 92e26dfc1a64d832ea64db13216de3025e4374bf \
  --artifacts build/advisor-latency-verification
```

Optional `--live` cases participate in both ranked-prefix and full-ranking
public/private equivalence checks. Fresh-process timings exclude imports and
startup. Actual-worker timings include snapshot copying and dispatch, but not
WebKit delivery. Functional scheduling tests verify coalescing, immediate
action priority, cancellation and keyed invalidation with controlled events;
they are not a live game-load performance benchmark.

The measured run used 92 committed cases and two optional local public snapshots
(1610, 1654), with one warmup and three measured passes per version. The warm
versions ran serially; each designated cold sample used a fresh interpreter,
alternating version order over three samples. All measurements and equivalence
runs kept the two-second budget; no baseline artifacts were reused.

| Measurement (ms) | Baseline | Optimized | Reduction |
|---|---:|---:|---:|
| Warm median, all 94 cases / 282 samples per version | 282.9 | 245.1 | 13.4% |
| Warm P95, all cases | 722.8 | 689.3 | 4.6% |
| Warm maximum, all cases | 924.1 | 886.5 | 4.1% |
| Serial 1643 warm median, 3 samples | 331.8 | 300.2 | 9.5% |
| Serial 1643 fresh-process median, 3 samples | 286.9 | 250.5 | 12.7% |

The optimized cold sweep completed all 94 cases with a maximum of 812.0 ms.
The 22 actual-worker cases all returned their expected status and stopped their
worker threads; submit-to-result median/P95/maximum were 611.3/648.6/827.7 ms.
There were no timeouts, samples over one second, or inconsistent repeated
outputs in the recorded performance runs. These are sample results, not a
guarantee under foreground, hidden-window or reconnect load.

Both ranked-prefix and full-ranking diagnostics compared **94 cases / 945
candidates** each. Public outputs (excluding only `elapsedMs`), list order,
recommendations, explanations and unrounded internal numerical fields were
exactly equal, with zero numerical changes and zero maximum absolute error.
The two historical timeout fixtures are reported separately but are included
in those totals, and completed under the same two-second budget.

After freezing the measurement sources, the branch was rebased onto the new
background-window fix at `f27931487e967372c414ec700942f45ba327a62d`. The measured
advisor and worker modules remain byte-identical. Only `autoplay.js`,
`background.js` and `monitor.py` differ from the measured tree; the integration
retains background activity and sends newly completed advice before the hidden
page pulse. The final bridge and background behavior is validated separately
from the inference measurements. The default reproduction command above runs
the 92 committed cases; the reported 94-case aggregate also needs the optional
local inputs.

[Machine-readable results](benchmarks/advisor-latency-20261007.json) preserve
the measured source hashes, runner/fixture fingerprints, integration source
hash, unchanged backend hashes, per-case cold and slow-sequence timings, worker
envelopes and complete equivalence summaries. Original game logs are not
committed.

Validation for this change: 451 source advisor/worker/benchmark tests passed;
the measured backend and these tests were unchanged by the subsequent rebase.
On the integrated tree, 303 Node tests and 24 Python bridge/background-activity
tests passed. The application built successfully and passed strict deep code
signature verification. Its frozen advisor suite collected 435 tests: 431
passed and four source-only benchmark-runner checks were skipped by design.

Native WebKit replay and overlay checks remain unverified in this execution
environment: replay received no events (`AssertionError: []`) and the overlay
check reported `WKErrorDomain Code=5`. The unchanged upstream `f279314` source
failed in the same way with the same fixtures. No online game or hidden-window
reconnect performance session was run, and no installed application was replaced.

## Recipient-aware rank preferences and consistent call previews (v11, 2026-10-07)

The baseline is `03b9c7ce99b9bccc5ce4b5059b243e39cd99e379`, including the
existing latency and autoplay changes. This update makes two policy changes:

- Predicted deal-in preferences retain the receiving opponent and actual
  predicted payment. The existing rank potential, smoothing, gain probe and
  weight bounds are reused. A separate signed `rankOpponentAdjustment`
  replaces the corresponding part of the old uniform preference; cash losses
  and danger probabilities retain their original meaning. Current defense,
  future policies, calls and replacement draws compare the same utility.
- Call previews no longer apply an additional 500-point cost that disappears
  as soon as a speculative future win probability becomes positive. The
  realized discard and its preview now use the same terminal utility. Legal
  no-yaku waits still have zero win income; structural tenpai can earn draw
  transfers. This is not a new rule to prefer or reject all no-yaku calls.

The new call fixture reproduces a preview that discarded a white-dragon pair
but changed to discarding 1m immediately after the call with no new external
information. All projected followup ledgers now match the realized window.
A separate synthetic rank fixture uses a score-gap pattern found in recent
logs: with self at seat 1 and scores `[25000,38000,40000]`, paying 8000 to last
crosses into last place, whereas paying 12000 to first does not. Equal modeled
hit probabilities now permit preferring the latter payment while preserving
the unmodified cash-loss estimates. These are consistency and preference
properties, not observed counterfactual match outcomes.

### Frozen local replay and limitations

The latest frozen log yielded 617 distinct executable `ready` windows,
selected without consulting later outcomes. Both source snapshots returned
617 `ready` results with zero timeouts. Thirteen recommendations changed:
six ordinary discards, six pass-to-pon choices, and one pon followup discard.
Best-policy labels changed in five windows: four fold-to-attack and one
attack-to-fold, including three windows with the same actual discard.

All six additional pons occur early, with 47–54 wall tiles remaining, and
their selected modeled policy has **zero self-win income**. Their advantage
comes from structural-tenpai draw receipts. The model does not fully price
future closed-hand riichi opportunities; a zero-win selected tail is not a
proof that every future legal winning route is impossible. These changed
calls require further policy evaluation and must not be presented as measured
improvements in win rate or rank-point yield. Complete match results were
used to prioritize the audit, not to fit new probability constants or attach
the realized result to unplayed alternatives. No installed App was replaced.

Across both replay versions, 11,414 candidate ledgers reconciled with maximum
score error below `5e-13`; terminal mass error was below `3e-15`. For 5,545
same-action ordinary discard/riichi/pass candidates, immediate danger and
cash expected loss were exactly unchanged. Replacement display metrics retain
their pre-existing rounded-child aggregation, so they are not substitutes for
the unrounded score ledger. The full local replay and private source logs are
not committed; the report records their input fingerprint and aggregate checks.

### Reproducible public regression and timing check

[Machine-readable summary](benchmarks/advisor-rank-transfer-20261007.json)
contains source and runner hashes, individual fixture hashes, candidate
ledgers, per-case samples and recommendations. The 21 cases combine 14
existing rank fixtures, five existing slow public snapshots, and the two new
regressions. Each version used a fresh interpreter, one complete warmup and
three measured passes, with full candidate ranking on both sides. This timing
run was separate from the full-suite and local-corpus processes.

| 63 measured samples per version | Baseline | v11 |
|---|---:|---:|
| Median | 320.9 ms | 331.5 ms |
| P95 | 613.0 ms | 694.7 ms |
| Maximum | 654.3 ms | 739.0 ms |
| Warmup or measured timeouts | 0 | 0 |

Repeated outputs were consistent in both versions. The extra policy work
increases calculation time on this sample; it remains below the unchanged
two-second budget. These results do not guarantee latency under all live
game or system loads.

```sh
python scripts/advisor_log_fixtures.py \
  --fixtures tests/fixtures/advisor_rank_cases.json \
  --fixtures tests/fixtures/advisor_performance_logged_cases.json \
  --fixtures tests/fixtures/advisor_call_consistency_cases.json \
  --fixtures tests/fixtures/advisor_rank_transfer_cases.json \
  --output /tmp/advisor-rank-transfer-cases.json
python scripts/advisor_compare.py \
  --baseline 03b9c7ce99b9bccc5ce4b5059b243e39cd99e379 \
  --fixtures /tmp/advisor-rank-transfer-cases.json \
  --warmups 1 --repeats 3 --output /tmp/advisor-rank-transfer-results.json
```

Validation on the final source: 468 advisor/worker/benchmark Python tests,
24 other Python tests, and 303 Node tests passed. New call regressions were
first observed failing on the baseline; rank tests cover payment thresholds,
opponent-score cache isolation, defense ordering, unknown-mode/saturated-soul
fallback, and current/future/abort/replacement accounting. An independent
positive/negative proportional-cost probe checked 126 real-state candidates
for omitted or duplicated rank adjustments; seven unknown-mode snapshots
preserved all compared numerical outputs across 61 candidates. Native WebKit,
packaged execution and live rank-point improvement were not tested by this
algorithm-only change.
