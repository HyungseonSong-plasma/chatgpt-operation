# Samuel cross-repository durable Issue controller — v1

## Scope and achieved stages

The existing [codeQA #92 real admission E2E](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/40231428604)
established `github:HyungseonSong-plasma/codeQA:issue:92`, six unverified
acceptance criteria and independent source/target identity attestation.
It did **not** persist a Controller work state or issue a code mutation.

This tranche separates four independently enforceable stages:

1. **Durable foreign-work ledger.** `cross_repository_workflow.ForeignWorkState`
   pins the repository-qualified work ID, issue-body SHA, target main SHA,
   criteria digest, monotonically checked revision, plan/action ID, bound
   target run receipt, Draft PR identity, CI evidence, and failure reason.
   A unique source Issue #220 marker holds the state. GitHub Actions bot
   identity is required; multiple or forged markers hard-stop. A new cycle
   independently re-attests Issue #92 before reconciling; an edited Issue
   or changed codeQA main becomes `revision_required`, not an implicit
   new authorization. Writes use exact-body compare-before-write,
   authoritative readback and serial source-workflow concurrency.
2. **Actual `SamuelController.run_cycle` entrypoint.** Only an explicit
   `foreign_snapshot` produced by authenticated codeQA readback may enter
   this branch. It never pretends to be source-local `issue:92`. Existing
   source Issue admission and state orchestration behavior are unchanged.
   Source `samuel-codeqa-foreign-cycle.yml` runs deterministic tests on PR;
   a manual mainline run reads live Issue #92, calls the Controller root and
   persists the source-owned foreign ledger.
3. **Reasoning → ActionPlan → distinct execution gateway.** A configured
   provider may produce an `IssueReasoningProposal`, compiled by existing
   `issue_reasoning_node` and `compile_guarded_action`, checked for exact
   repository-qualified work ID, then validated against a *separate*
   codeQA source/test path policy. Plans are only `review_required`
   until an owner-approved, enabled policy and exact ActionPlan ID/revision
   authorize dispatch. The target-scoped gateway requires the distinct
   codeQA transport, live pinned main SHA and exact target-owned
   `samuel-codeqa-issue-execute.yml` workflow, then records real dispatch
   correlation. The target executor workflow is **not installed or enabled
   in this tranche**, so no source-code mutation is currently possible.
   The candidate policy in this PR has `enabled:false`.
4. **CI → evidence → revision.** A target-owned execution receipt must
   match the work ID, ActionPlan digest, source run, pinned base, single
   Draft PR and its immutable HEAD. Independent codeQA PR CI runs must
   match exact head SHA, branch and required workflow filenames. All
   required success produces `ci_verified` (not `complete`); missing
   evidence produces `ci_pending`; failure/cancel/skip produces
   `revision_required`. No Issue closure or merge is possible through
   this flow.

## Manual durable-ledger proof

After the source implementation PR is reviewed/merged, run:

[Samuel → codeQA Durable Issue #92 Cycle](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/workflows/samuel-codeqa-foreign-cycle.yml)
→ **Run workflow** → **main**.

Expected first live outcome: `SAMUEL_FOREIGN_CYCLE=FOREIGN_LEDGER_CYCLE_VERIFIED`;
source Issue #220 receives a *new* `github-actions[bot]` state comment,
initial revision 0 and `phase=reasoning_required`; source artifact
`samuel-codeqa-foreign-cycle-<run_id>` attests the comment ID and SHA.
Repeating the manually dispatched workflow with unchanged Issue facts
returns a source ledger `NOOP`, avoiding duplicate comments and phantom
actions. If the token or Issue facts are wrong, it must fail closed.

This manual workflow deliberately keeps semantic reasoning disabled
and the separate target write policy disabled. It is a safe **state
persistence proof** rather than a complete automated #92 implementation.

## Remaining gated work

- Review and install a target-owned codeQA execution workflow that
  independently verifies the trusted source workflow run and action/target
  scope; without this, `dispatch_foreign_action` rejects the request.
- Owner-review/enable a separate *target code* policy (the one-file
  documentation proof policy cannot authorize real `src/`, `tests/`,
  `fixtures/` writes).
- Provision/configure the existing semantic reasoning provider if
  required; do not synthesize claims or accept raw Issue instructions.
  Enable foreign provider-driven planning only after owner review.
- Demonstrate live ActionPlan execution, exact-head target CI
  and target-owned receipt before claiming autonomous codeQA development.
  Actual external SDK/consumer/DB compatibility evidence remains
  missing and Issue #92 must remain open.
- Only a separate reviewed merge authority can change codeQA main;
  this tranche does not offer or silently grant one.
