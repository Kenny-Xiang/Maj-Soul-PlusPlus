# Offline advisor evaluation

The comparison runner evaluates identical public snapshots against two advisor
source versions. It never opens the game, connects to game servers, or submits an
action. It measures reproducibility, rule regressions, recommendation changes,
and local calculation time; it does not establish stronger play or calibrated
win probabilities.

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
