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
sanma snapshot from `turn.json`. The 18 cases cover ordinary efficiency, a broad
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

The initial local smoke comparison on 2026-10-04 used source `59a30d5`, all 18
cases, one warmup pass, and five measured passes (90 samples per version).
Both identical source versions produced the same candidates and recommendations.
Baseline median/P95/maximum were 1.252/28.194/29.751 ms; the working-source copy
measured 1.308/28.108/29.386 ms. These are a small warmed sample on one machine,
not a performance guarantee. A separate comparison against pre-fix commit
`33afbb4` detected the changed `new-riichi-changed-waits` recommendation, confirming
the report also captures a real historical behavior change.
