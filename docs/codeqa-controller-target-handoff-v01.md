# Samuel → codeQA #92: governed read-only E2E preflight

**Contract:** `automation/samuel/codeqa-readonly-target-v1.json`.
**Scope:** source `HyungseonSong-plasma/chatgpt-operation#220` to target
`HyungseonSong-plasma/codeQA#92`, task ID
`github:HyungseonSong-plasma/codeQA:issue:92`.

The current flow is a **preflight**. It does not authorize or perform codeQA
file writes, PR creation, merging, issue closure or real SDK-contract acceptance.

## Live chain

1. Samuel `samuel-codeqa-preflight.yml` fetches GitHub's live source and
   target Issue JSON and both repository `main` SHAs; it validates a
   closed-world, separately versioned *read-only* target policy, approved
   actor, source Workflow Run ID and repository-qualified work ID.
2. A PR-triggered Samuel run stops after confirming the **read-only plan**.
   This is a real live *metadata* E2E test, but **not** a Controller-origin
   GitHub dispatch.
3. An owner-invoked `workflow_dispatch` can attempt the next hop only if
   the Samuel repository has an owner-managed Actions secret named
   `SAMUEL_CODEQA_DISPATCH_TOKEN`. This must be a narrowly scoped
   GitHub App or fine-grained user token with *Actions: Read and write* on
   the **codeQA** repository, and preferably no contents or PR write
   permission. Samuel's ordinary per-repository `GITHUB_TOKEN` cannot
   authorize a write/dispatch to codeQA.
4. If the token is absent, execution fails with
   `BLOCKED_MISSING_TARGET_ACTIONS_TOKEN`; it does not report success.
5. If configured, Samuel dispatches **only**
   `codeQA/.github/workflows/samuel-crossrepo-preflight.yml` on `main`.
   It must observe exactly one correlated target Run and an independently
   generated codeQA receipt. SHA, work ID, source Run ID, target outcome,
   origin and read-only scope must match; partial/missing evidence blocks.
6. The receiving workflow independently fetches source #220, target #92,
   both repository HEADs and, for a real dispatch, the actual originating
   Samuel workflow Run. This prevents merely copying a claimed origin ID.
   It never modifies codeQA.

**Run-bound authority:** A `READY_FOR_READ_ONLY_DISPATCH` plan is not
`DISPATCH_REQUEST_ACCEPTED`, which is not `TARGET_READ_ONLY_E2E_CONFIRMED`.
No stage can be silently promoted to the next without a matching GitHub
observation and artifact.

## Important remaining Controller work

This setup provides a governed source/target **handshake** and executable
dispatch/readback workflow, but it is not yet integrated as a native
`ControllerCommand` issued from Samuel's durable issue ActionPlan.
The existing central `repository-mutation-policy.json` remains unchanged
and **still forbids** cross-repository source mutation. Closing codeQA #92
requires actual SDK/API/DB evidence independently of this transport.

Follow-ups for full #220: (a) owner-managed target Actions credential and
successful authenticated dispatch; (b) concrete, durable, issue-specific
Controller ActionPlan issuance; (c) independently reviewed target mutation
authorization and exact PR SHA/CI validation; (d) verified persistence,
recovery and completion. Do not auto-merge a preflight PR as evidence
of a Controller-origin worker action.

**Tests:** `tests/test_cross_repo_preflight.py` and Samuel PR CI; target
receipt and negative controls in codeQA PR #111.
