# Samuel #220 — codeQA Controller activation gates

This document deliberately separates evidence of the connected ChatGPT GitHub
App from GitHub Actions runner credentials. Repository visibility and a successful
direct-Connector codeQA PR are **not** central Controller-origin write evidence.

## Verified on 2026-10-25

- The connected GitHub App installation `155128539` lists both
  `HyungseonSong-plasma/chatgpt-operation` and
  `HyungseonSong-plasma/codeQA`.
- The exact codeQA repository ID is `1424293498`.
- Existing source read-only workflow: `.github/workflows/samuel-codeqa-preflight.yml`
  and target receiver: `codeQA/.github/workflows/samuel-crossrepo-preflight.yml`.
- Existing connector-origin **draft** target [PR #112](https://github.com/HyungseonSong-plasma/codeQA/pull/112)
  at `3b12a741ed7d124b8189558c24cef5a8c1088c43` passed five
  target PR workflows; **not** Controller origin.
- New PR [#223](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/223)
  adds a guarded live target reader and rejected-request tests. The target
  write candidate is **disabled**, and cannot grant permission.
- New `samuel-codeqa-write-preflight.yml` has a **PR test mode** (no
  runtime credential access or target writes) and a separate manually
  dispatched, live-readback-only mode. A green PR run is **not** live
  credential verification.

## Owner-controlled credential prerequisite

The prior read-only dispatch workflow needs an independently issued GitHub
Actions secret in the **source** repository:

- Secret: `SAMUEL_CODEQA_DISPATCH_TOKEN`
- Restrict to repository `HyungseonSong-plasma/codeQA`, GitHub Actions:
  **Read and write** only, repository metadata as GitHub requires.
- This credential should **not** have target Contents, Pull requests, Issues
  write or Administration rights.

In GitHub, the owner configures the secret in
`chatgpt-operation → Settings → Secrets and variables → Actions → New repository secret`.
Never put a token in this repository, an Issue, a PR, or chat.

Then run
`chatgpt-operation → Actions → Samuel → codeQA Governed Read-only Preflight
→ Run workflow` on `main`. Require a real source `workflow_dispatch` run,
uniquely correlated target `workflow_dispatch` run, exact HEAD SHA,
non-skipped success, and downloaded target-owned read-only receipt.
Without this proof, remain `TARGET_READ_ONLY_E2E_UNVERIFIED`.

## Separate candidate write-readiness gate

**Do not create or install a write credential merely because read-only passed.**
After reviewing and explicitly accepting the separate codeQA write capability:

1. Provision a target-scoped `SAMUEL_CODEQA_WRITE_TOKEN` as an Actions secret
   in `chatgpt-operation`, with target Contents read/write, Pull requests
   read/write, and Actions read as required; no administration or merge grant.
2. Review and enable only the distinct
   `automation/samuel/codeqa-write-target-candidate-v1.json` in a PR with
   current exact target base SHA. It is initially `enabled: false`.
3. Dispatch `Samuel → codeQA Write Readiness (no mutation)` on `main`.
   The trusted workflow fetches its own run ID via the central GitHub API,
   verifies event, actor, path and SHA, re-reads both real Issues and
   live target repository ID, token-reported push permission, base SHA and
   exact workflow path. The output is zero-mutation evidence, **not**
   an executed Controller ActionPlan.
4. Implement and review a bounded Controller ActionPlan-to-write executor:
   independently trusted Issue #92 ingress, exact branch creation, isolated
   doc-only file change, draft PR, postcondition readback and exact-head
   required CI evidence. Preserve separate merge authorization.
5. Independently verify actual target write/PR permission and the Controller
   execution receipt before claiming codeQA mutation E2E. Missing/stale
   credentials, skipped CI, unmatched run identity, a `None` ActionPlan,
   or unreviewed policy all remain hard blockers.

A successful *read-only* permission probe **does not prove actual write or
PR-create permission**. Neither staged workflow automatically merges PRs,
closes codeQA #92 or changes central protected mutation policy.
