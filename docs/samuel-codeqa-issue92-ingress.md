# Samuel → codeQA #92: authenticated Issue planning

## Purpose

The authenticated, owner-dispatched [bounded codeQA write proof](https://github.com/HyungseonSong-plasma/codeQA/pull/114)
verified a real branch, one documentation file, a Draft PR, exact-head Layout
CI and action receipts. That proof does **not** implement the pending
real [codeQA Issue #92](https://github.com/HyungseonSong-plasma/codeQA/issues/92).

The next necessary boundary is a **repository-qualified work identity**
`github:HyungseonSong-plasma/codeQA:issue:92` and real issue ingestion.
Native source repository Issues retain existing `issue:N` IDs and cannot be
silently confused with cross-repository Issue numbers.

## Trusted source to typed planning

The source-owned `samuel-codeqa-issue-plan.yml` workflow:

1. Reads its own run ID, source branch `main`, SHA, author and workflow path
   independently from GitHub.
2. Reads live source Issue #220 and codeQA Issue #92. Both must remain actual
   open Issues, with correct API URLs.
3. Independently reads codeQA repository ID, default branch, expected
   commit SHA and active `layout.yml`, under the exact previously
   owner-reviewed target policy; stale target SHA or missing credential
   fails closed.
4. Extracts the **five real acceptance criteria**, pins the exact target
   Issue body SHA256 and invokes the same `plan_admitted_issue` envelope
   constructor used by `SamuelController.run_cycle`. Locked architecture
   decisions are loaded from the source-controlled `decisions.json`.
5. Emits a structured `samuel-codeqa-issue-admission.json` artifact with
   the verified scope and reasoning context. The raw untrusted body is omitted
   from the outward-facing reasoning context; its exact SHA is preserved.
   All acceptance criteria are marked **unverified** unless later
   independently admitted completion evidence proves otherwise.

The result is `REASONING_REQUIRED_NO_EXECUTABLE_PLAN` and **not**
`COMPLETE` or `PASS`. This boundary grants *no executable target write
authority*. PR-mode runs only offline adversarial tests; authenticated
readback runs only on manual mainline `workflow_dispatch`.

## Necessary next step: authorized issue execution

The current codeQA write policy is deliberately **a single proof document
only**. It cannot be reused as permission to mutate `src/`, `tests/`,
`fixtures/` or production compatibility contracts.

To implement real Issue #92 autonomously, a separate reviewed tranche must:

- Take the qualified Issue snapshot into a durable, repository-qualified
  workload ledger and `SamuelController.run_cycle`, without spoofing a
  source-local `issue:92` event.
- Invoke a configured semantic reasoning provider and require an actual,
  validated, narrowly scoped `ActionPlan`, not only a plausible proposal.
- Obtain a separately reviewed target mutation policy governing exact codeQA
  files and required independently trusted static/runtime CI. Reject all
  missing provider, SDK, consumer baseline or migration evidence.
- Correlate every actual target PR head, CI run, analysis finding,
  acceptance evidence and action ID to the durable source/controller cycle.
- Keep the merge permission separate and unavailable in this workflow.
  Neither source Issue #220 nor target Issue #92 should be closed from this
  planning artifact or from the earlier fixed-document Draft PR.

This read-only stage can be retried without mutating codeQA or reproducing
the earlier proof branch's non-idempotent file creation.
