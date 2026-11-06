# David Evolutionary Arena: evidence, semantics, and v0.2 evaluation contract

**Issue:** [#246](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/246).  
**State:** v0.1 read-only implementation + proposed v0.2 contract.
Owner has **conditionally approved** future v0.2 branch competition **only after
all admission prerequisites are satisfied**; this is NOT permission to start
candidate branches now.
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

## 5. Owner-selected codeQA pilot scope — documentation-reference impact

**Owner-selected task:** [codeQA #288](https://github.com/HyungseonSong-plasma/codeQA/issues/288),
**phase 2 only**: improve documentation-reference **impact analysis** without
moving or rewriting existing docs. Do NOT duplicate [active PR #289](https://github.com/HyungseonSong-plasma/codeQA/pull/289),
which already implements phase-1 inventory/catalog, a portal and a bounded
tracked-reference audit. Build from the finally accepted phase-1 codeQA
`main` SHA after ordinary review/merge; do not silently base on a floating
`main` or an unmerged PR snapshot.


**Confirmed owner selection (2026-11-05):** codeQA documentation-reference
impact analysis is the first competition task. No further task-selection
decision is needed. Exact common base, independent baseline/oracle,
replay-safe competitor capabilities, time/cost budget and trusted reviewer
authority are still **unresolved**, so this selection alone permits no
candidate branch creation. GitHub PR #289 owns the phase-1 audit and may
change while under review; the DEA baseline must come from an adopted
immutable codeQA revision rather than a draft.

**One output contract for three genuinely distinct implementations:**

- `A — FULL_SCAN`: exhaustive deterministic full-corpus reference analyzer.
- `B — REFERENCE_GRAPH`: materialize a versioned path/fragment backlink graph;
  compute impacted consumers by graph traversal.
- `C — INCREMENTAL_INDEX`: preserve a content-addressed dependency index;
  update only changed sources and independently cross-check against full scans.

The unchanged baseline, A, B, and C must share the **same exact initial
codeQA source commit**, analyzer/profile/oracle pins, test cases, output
schema, permitted operations, fixed CI environment and equal development
budget. All candidates must prove complete enumeration under their claimed
scope; a fast-but-incomplete analyzer is **infeasible**, not the winner.
Alternatives are designs to test, not verified viable improvements.

**Scope of bounded semantic equivalence for this pilot:**

1. Freeze a reference corpus of all tracked relevant Markdown plus
   source/config/test references to docs paths and Markdown fragments.
   Capture full `(source path, source line, link text/target, resolved path,
   fragment, status, provenance)` observations with exact source identities.
2. Compare each candidate against a **separately tested independent oracle**
   on the same corpus, including reference-style links, relative segments,
   percent encoding, duplicate headings/slugging, fenced code, fragments,
   malformed paths, missing targets, literal path references, and intended
   synthetic/absent paths. No dropping erroneous inputs.
3. Require exact preservation of existing document bytes, existing public
   codeQA API/CCG/QA contracts, package roles, root layout, and repository
   policy. No physical relocation, content rewriting, schema migration,
   branch deletion or merging in the Arena.
4. Confirm known internal consumers (source/config/tests/install/scripts),
   declared authority/status labeling and stable entrypoint/backlink
   behavior. For external URLs, untracked deep links and externally hosted
   consumers, record `NOT_EVALUATED`, never equivalent/PASS.
5. Independent exact-HEAD readback must authenticate actual outputs and
   observations. The current metadata-only comparators cannot validate
   receipt origin by themselves. Missing required observations => UNKNOWN;
   a real discrepancy => FAIL; matching frozen scope => PASS_BOUNDED only.

**Candidate fitness metrics:** verified completeness and correctness are
hard gates. After these pass, compare measured wall time under a frozen
runner/protocol, peak memory, analysis/recomputation work, code complexity
proxy and change footprint as separate objective vectors. Never collapse to a
scalar or claim the docs navigation itself improved solely because an
internal analyzer is faster. The exact benchmark repetition count and
resource budget must be frozen before candidate work. Missing comparable
metrics => UNKNOWN, not zero.

**Current source checkpoint (not the future base):** codeQA `main` was
`23c2166bd3b2b0c825b207e856b95c68e0e24070` and PR #289 was
`5845d7505f22b90d9cb6a9174c13b58b5e04f68c` when this pilot was
first proposed. PR #289 is not merged at this checkpoint and does not authorize
candidate creation or source migration.


**Independent Oracle status (2026-11-05):** A separate read-only reference
scanner and immutable Git-object observation path now exist at
src/chatgpt_operation/controller/dea_reference_oracle.py, with golden,
negative, real-codeQA-preview and incremental-transition tests. See
docs/dea-v02-reference-oracle.md. This establishes only a **bounded,
source-grounded observation subset**. A trusted candidate-output runner,
complete required Markdown/consumer scope, independently authenticated
candidate receipts and accepted codeQA base are still NOT_EVALUATED.
Therefore trusted_semantic_oracle_ready remains false, and no candidate
branch competition is authorized.

## 6. Remaining v0.2 admission gates

1. **Confirm distinct implementations.** The owner has selected codeQA #288
   phase-2 documentation-reference impact analysis. Validate that A/B/C are
   materially distinct but equivalent on the same frozen contract and do not
   duplicate or change the existing phase-1 audit semantics in PR #289.
2. **Finish v0.1 review and admission.** PR #249's exact-HEAD CI passed,
   including the read-only real codeQA replay. The owner postponed adding a
   Gemini/third-party independent reviewer; this review is **pending**, not
   waived or satisfied by AI self-review. Keep PR #249 draft and unmerged
   until the applicable independent review/owner authority is satisfied.
3. **Freeze consumer baseline.** PR #289 must complete its ordinary review
   and adoption, or the owner must separately choose a valid immutable
   alternative. Re-evaluate its final codeQA HEAD, exact documents and
   link audit before fixing the common Arena base.
4. **Prove semantic oracle and receipt origins.** Build a trusted independent
   behavior/reference runner, negative controls, exact-HEAD authenticated
   source/CI artifact receipts and a fixed case/consumer scope. External
   unknowns cannot be promoted into PASS.
5. **Budget/fit.** Confirm A/B/C distinctness and policy admissibility, then
   freeze same-runner measured repeat count, time/model/cost limits,
   acceptance hard gates and stopping rules. Initial pilot should use one
   generation only, with no external paid LLM API by default.
6. **Promotion remains separate.** Human/independent review and normal
   Samuel PR-create/merge authority still govern any champion. Owner's
   conditional competition approval is **not** David-generation approval,
   issue closure, policy rewrite, or blanket license for repository writes.

Until these gates are proved from fresh evidence: **v0.2 execution is
CONDITIONALLY_APPROVED_BUT_BLOCKED**, with **zero candidate branch actions
authorized now**. Documentation and read-only evidence/test development may
continue without treating the blockers as resolved.


## 7. Read-only candidate Artifact evidence milestone

The existing Draft PR #249 now includes a GitHub Actions Artifact metadata/ZIP
verifier, token-safe read-only downloader, source/semantic readback coordinator
and a fail-closed Fitness semantic gate projection. See
docs/dea-v02-artifact-provenance.md. Synthetic integration tests link a run's
exact candidate HEAD, Artifact ID/digest and the separate immutable source
SHA; the trusted source Oracle rejects forged output records.

**Do not interpret this as a verified production candidate:** no
independently attested Artifact-producing Job or protected producer workflow
has been configured or executed, and producer/job identity remains
NOT_ATTESTED. Candidate performance metrics are treated as untrusted.
The projected semantic Fitness gate can be FAIL or UNKNOWN, never PASS, until
the independent producer/runner and workflow attestation requirement is
satisfied.

The adopted Samuel mutation policy forbids editing .github/workflows/**
in this scope. No workflow file, permission rule, branch competition or merge
was changed. Approval for a separate protected producer/attestation
workflow remains an explicit future gate.
