# David Evolutionary Arena: evidence, semantics, and v0.2 evaluation contract

**Issue:** [#246](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/246).  
**State:** v0.1 read-only implementation + proposed v0.2 contract, **NOT v0.2 execution approval**.
No champion, merge, branch population, policy change, external API/model call or David promotion is authorized here.

## 1. Avoid a single quality number

`dea_v01_fitness.evaluate` accepts an immutable `work_id`, common
`base_sha`, unchanged `baseline_id` and exact protocol pins:
`analyzer_sha`, `profile_sha`, `oracle_sha`, `measurement_set_sha`.
Every candidate needs a separate exact `head_sha` and every gate/metric
receipt must bind that HEAD and all four protocol identities.

**Order:**

1. Hard gates: `ci`, `semantic_contract`, `policy`, plus any task-specific
   gates fixed **before** development. `FAIL` => `INFEASIBLE`; `UNKNOWN`
   => `UNKNOWN_HARD_GATE`. Missing gates reject the contract.
2. Metric completeness: each metric has fixed direction `min` or `max`,
   compatible measurement denominator and evidence ref. `null` =>
   `UNKNOWN_METRICS`, not zero or a free win.
3. Eligible complete vectors only: A dominates B iff it is no worse in every
   metric and strictly better in at least one. Return **all non-dominated
   trade-offs**, preserve the untouched baseline and prohibit automatic
   champion selection. Do not produce a weighted aggregate score.

**Important:** the module enforces *submitted metadata consistency*. It does
**not** authenticate GitHub evidence URLs, check-suites, artifacts, provenance
signatures, owner approvals or test runner integrity. Result state is
`METADATA_ELIGIBLE_NOT_ATTESTED`; review is provisional. A future trusted
readback adapter must verify all evidence before real candidate selection.

## 2. Semantic compatibility is a scoped, evidence-based claim

Finite tests cannot prove arbitrary programs semantically equivalent.

`dea_v01_semantics.compare_observations` requires immutable baseline/head
SHAs, identical oracle, input-set and environment SHAs, identical case IDs and
input digests, and captured **returns, exceptions, and side effects**.
Each case records an externally produced observation digest with status
`OBSERVED`, `UNKNOWN` or `ERROR`.

- Same observed output on **all declared cases** => `PASS_BOUNDED`.
- Any observed discrepancy => `FAIL`.
- Missing, errored or differently enumerated cases => `UNKNOWN`.
- Different inputs, oracle, environment or required capture dimensions =>
  reject as an incomparable protocol.
- Even `PASS_BOUNDED` leaves universal equivalence `NOT_PROVEN` and
  external/dynamic consumers `NOT_EVALUATED`.

The comparator does not run the target programs or cryptographically
authenticate the submitted observation hashes. A separate trusted behavior
runner is a **hard prerequisite** before any real candidate semantic gate
can claim PASS. This gate must also cover the admitted API and known consumer
contract; unknown mandatory consumers prevent automatic promotion.

For codeQA's Pipeline Git subprocess cleanup: test historical pinned trees,
empty/invalid inputs, ordering, byte identity, exceptions and public Naming
entrypoints on old and new code against identical cases. Independently check
the module boundaries, known callers, wheels/public API and side effects.
Baseline and candidate observations must come from separately executed
exact-SHA sources with independently read-back receipts. A green CI check for
the new version alone is insufficient.

## 3. Historical codeQA pilot: known facts, bounded unknowns

- Before: `fb54b6c92363476b07a726008fbe8c1ab35f1a6a`
- After: `6aa15e8613b95bf39233a7b191a730f257d7adb3`
- Same 12 tracked Pipeline Python files; independently inspected source
  facts: direct `subprocess` import sites **2 => 0**.
- Source role policy retains Pipeline composition and Infrastructure Git
  access. B8 static Pipeline import proxy remains **43/48**; zero B4 viable
  package move proposals (3 occupied targets, 2 forbidden directions).
- [Merged codeQA PR #188](https://github.com/HyungseonSong-plasma/codeQA/pull/188)
  and [B8 run #42000776739](https://github.com/HyungseonSong-plasma/codeQA/actions/runs/42000776739)
  are historical, source-scoped evidence. The CI-only real Git-object replay
  test fetches the immutable after commit and checks both original blobs and
  matching 12-file denominator. Its **actual execution must be verified from
  that PR's exact-head CI**; adding the test is not evidence that it passed.
- This historical before/after is **not** a fair three-strategy Arena contest.
  `external_consumers=NOT_EVALUATED`; universal semantic compatibility is
  not proven. Never treat the after commit as an Arena champion.

## 4. v0.2 evaluation protocol — three strategies (design contract only)

**Population:** one unchanged baseline `BASE` plus **three new, materially
different strategies** `A`, `B`, `C`, independently based on an identical
pinned source commit. No fake variants. Each candidate has a typed design
manifest: intent, affected files, ownership/interface changes, reusable
genes, compatibility constraints, known failure risks and planned tests.
The source role profile, tests, metrics, accepted APIs and measurement
protocol must be frozen **before** any candidate work.

**Fairness:** same oracle, exact pinned analyzer/profile, fixtures,
environment, allowed time/model/compute budget, number of iterations,
performance trials and trusted CI check set. Isolate branches and durable
checkpoints, time-slice the single model, compare exact HEADs, and cap future
generations at three. Do not count repeated judgments by the same LLM as
independent reviewer approval.

**Fitness sequence:**

1. Authenticate branch/base/head and each metric/gate artifact independently.
2. Evaluate task-specific correctness, safety/policy, API/consumer scope and
   behavioral-contract hard gates. Any FAIL or UNKNOWN blocks eligibility.
3. Confirm exact HEAD and identical denominator, protocol and units before
   comparing all quantitative metrics.
4. Identify Pareto survivors, preserve elite and unchanged baseline, report
   uncertainty and non-dominated trade-offs without artificial scalar score.
5. Preserve lineage and all evidence. Features from losers remain *hypotheses*
   until separately verified for interface/state/invariant compatibility.
6. Review independently, obtain owner approval as required and use normal
   Samuel connector-only PR-create, CI/review and merge gates.
   A Pareto review set never grants mutation authority.

**Stop:** missing credible evidence, incompatible snapshots, failed hard
constraints, exhausted compute budget, observed stagnation, blocked
permissions/authority or owner hold. No unreviewed branch cleanup.

## 5. Remaining v0.2 admission decisions

1. Select one genuinely appropriate task with **three noncolliding,
   policy-compliant alternatives**. The original #184 package move candidates
   are rejected; do not relabel them as viable.
2. Specify which known and external consumers must be included in a scoped
   semantic acceptance oracle. Missing mandatory coverage blocks automatic
   champion qualification.
3. Freeze actual cost/time caps, repeat counts and noisy metric handling.
4. Establish independent owner/reviewer authority for public API changes
   and champion promotion.

Until these are resolved: **v0.2 is a validated design/fixture contract,
not an authorized population or automated development campaign**.
