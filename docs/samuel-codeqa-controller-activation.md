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

## Implemented bounded write-proof lane (2026-10-25)

Source-only implementation:
- `src/chatgpt_operation/controller/codeqa_governed_write.py` produces three
  typed, deterministic `ActionPlan` objects after separately reading the
  actual source Controller run and both GitHub Issues.
- `.github/scripts/codeqa_governed_write.py` uses the scoped target credential
  to execute exact-target branch and file actions using the existing mutation
  engine, open a **Draft** PR only, and validate exact HEAD and `layout.yml`
  PR CI. Success is evidenced by an Actions receipt artifact.
- `.github/workflows/samuel-codeqa-write-execute.yml` runs negative tests on
  pull requests **without credentials or target mutations**. Its
  `workflow_dispatch` stage is fail-closed unless invoked on source `main`,
  the source run/actor/path/commit are independently verified, the
  fixed target policy is explicitly enabled, and a distinct
  `SAMUEL_CODEQA_WRITE_TOKEN` exists.
- `automation/samuel/codeqa-write-target-candidate-v1.json` remains
  **`enabled: false`**. It pins target repo ID, `main` base commit,
  exact isolated branch, a single `docs/samuel/` file, required `layout.yml`
  and a closed operation allowlist. The protected central mutation policy
  is unmodified.
- PR readback requires `draft: true`; no `merge_pr`, issue closure, workflow
  modification or general-purpose file mutation can be requested.
- Runtime CI is correlated using independently read target PR number,
  exact PR head commit and branch, rather than the often-empty
  GitHub Actions `pull_requests` array. Only named `layout.yml` success
  is required for this **bounded proof**, not full codeQA release acceptance.

**Important provenance distinction:** These plans originate deterministically
inside an owner-dispatched Controller-owned workflow and are not arbitrary
user-supplied `plan_json`. This is **not yet** Samuel's full durable Issue
#92 admission → autonomous `SamuelController.run_cycle` → execution
gateway → target code changes. That requires a separate reviewed controller
task-routing tranche after this bounded E2E.

### How to activate the isolated write proof

1. Review and merge the guarded implementation PR **with the target policy
   disabled**. Run CI on the exact implementation head first.
2. Owner provisions a **separate** fine-grained token with **only codeQA**
   repository access. Target permissions: Contents read/write, Pull requests
   read/write, Actions read, Issues read, Metadata read. Do not enable repo
   administration or repository workflow modifications. Save it as
   `SAMUEL_CODEQA_WRITE_TOKEN` in **source chatgpt-operation** Actions
   secrets. Preserve the previously verified read-only
   `SAMUEL_CODEQA_DISPATCH_TOKEN` unchanged.
3. Separately approve a reviewed policy PR changing only `enabled` to true
   and, if codeQA `main` moved, repin exact `base_sha` based on current
   authenticated GitHub data. No wildcard paths, additional operations,
   workflow edits or automatic merge.
4. On source `main`, manually trigger
   `Actions → Samuel → codeQA Governed Draft PR Proof → Run workflow`.
   PR-triggered tests never execute the target mutation. A missing/stale
   credential or policy results in `HARD_STOP` and no authorization.
5. Verify the resulting source run, codeQA branch, **Draft** PR, exact PR
   head, required target CI success and saved ActionPlan/operation IDs. Do
   not merge the codeQA proof PR without separate human review. Only after
   live success can this isolated proof be marked complete.

This implementation does not grant auto-merge, background execution or
unbounded Controller work. Never reuse the dispatch-only token for writing.
