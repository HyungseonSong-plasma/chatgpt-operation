# DEA #254 — GitHub-native protected Workflow adoption (no external Trusted Host)

**Status: OWNER-OPERATED ADOPTION PLAN, REVIEWABLE; NOT EXECUTED.**
**Owner choice (2026-11-06):** use existing GitHub protections, GitHub Actions
and the ChatGPT GitHub connection for *ordinary permitted work*; do not
deploy an external Trusted Host, independent model-facing GitHub App, or
ChatGPT operator-grant server for this one-time smoke Workflow adoption.

Related: Issue #254, original review-only approval
https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/254#issuecomment-6685977537 .
That prior owner comment explicitly authorized **preparation for adoption review**,
not the protected Workflow write, final merge, Environment deployment approval,
or exemption from any currently effective policy.

## 1. Separation of responsibilities

- **Human owner `HyungseonSong-plasma`** retains competent repository policy
  authority; prepares/authorizes the **one** protected Workflow introduction
  using their independently authenticated GitHub account and an ordinary
  reviewable GitHub PR; personally reviews/merges when authorized; personally
  reviews the protected Environment deployment. A human review must never
  be impersonated by the ChatGPT GitHub integration.
- **ChatGPT** does preflight, source verification, permitted `src/`,
  `tests/`, `docs/` changes, ordinary reviewable PRs, CI inspection and
  post-deployment read-only artifact/attestation evaluation. It may prepare
  exact copy instructions and review evidence, but **must not write**
  `.github/workflows/**` through the existing connector, repository-native
  engine, Git-data fallback or any alternative provider.
- **GitHub** enforces the protected `main` PR/CI Ruleset and, when
  independently configured, the `dea-human-break-glass` Environment gate.
  The existence of an Environment name is not proof the reviewer/branch
  settings or approval were enforced.

**No blanket automation policy exception is part of this design.**
Keep `automation/samuel/repository-mutation-policy.json` and its
`.github/workflows/**` denial **unchanged**. Keep the repository-native
hardcoded Workflow write stop unchanged. Therefore old policy PR #259 and
external-host code PR #262 are superseded and MUST NOT be merged to
activate this approach.

## 2. Exact one-time human adoption scope

| Field | Bound value |
| --- | --- |
| Repository | `HyungseonSong-plasma/chatgpt-operation` |
| Work identity | `DEA-254-PRODUCER-SMOKE` |
| Reviewed source on protected `main` | `docs/dea-v02-protected-producer-smoke.proposed.yml` |
| Source Git blob | `8215bb3d07f3918c6a3ecd9f92e152538625691a` |
| New Workflow path | `.github/workflows/dea-evidence-producer.yml` |
| Human-created branch | `issue-254-producer-adoption` based on fresh `main` |
| PR | Draft, targeting `main`, exactly one added file |
| Effect | Non-candidate signed Artifact smoke only |
| Deployment | `dea-human-break-glass`, named human approval |

Source implementation PR #249 was **merged** on 2026-11-06. The Workflow
file is deliberately absent from `.github/workflows/` until human adoption.
The intended branch was read back as absent on 2026-11-06; recheck live state
before acting. Commit SHA and Actions versions MUST be freshly reverified
before the protected PR is merged.

## 3. Owner-only GitHub-native handoff

Before any write, the human owner reviews this scope and confirms that
**a distinct, human-initiated protected Workflow adoption PR is an eligible
authorized path** under current repository governance. If their policy
authority does not permit that exception, STOP and seek formal owner policy
adoption. Do not treat chat instruction or Issue comments as proof of a
GitHub write permission.

### Option A — GitHub web UI

1. Sign into GitHub as `HyungseonSong-plasma`; view current protected
   `main` and the exact reviewed source YAML above. Check the source Git
   blob identity, SHA-pinned Actions and one-run-only smoke scope.
2. Create branch `issue-254-producer-adoption` from **current main**.
   Confirm the target Workflow file does not exist.
3. In that branch, create **one file only** at the exact Workflow path,
   copying the source YAML verbatim from the same verified main snapshot.
4. Open a **Draft PR** into `main`; reference #254 and the exact
   owner-controlled adoption decision. Inspect `Files changed`: one
   added file, not a policy mutation, existing Workflow modification,
   branch protection change or source-code side effect.
5. Check live CI on the **exact PR head SHA** and independent technical /
   security review when applicable. Human owner makes the ordinary
   reviewed merge decision in GitHub; no bot/admin bypass or self-approved
   model review.
6. When deployed on `main`, the owner dispatches the **one** smoke run on
   exact current `main` with matching `expected_main_sha`. The
   `dea-human-break-glass` deployment approval must be executed
   personally by the eligible named GitHub human after verifying the
   waiting job and commit.

### Option B — equivalent owner-authenticated local GitHub CLI

These are **instructions for the human to run**, NOT a command for
ChatGPT/repository-native Actions to execute. Use the owner's existing
authenticated workstation; never provide a token or credential in chat.
The commands require a clean local clone and a **new** branch name:

```bash
set -euo pipefail
gh auth status
git status --short
# STOP unless the checkout is clean and the repo's owner is correct.
gh repo view --json nameWithOwner --jq .nameWithOwner
git fetch origin main
git switch -c issue-254-producer-adoption origin/main

test "$(git hash-object docs/dea-v02-protected-producer-smoke.proposed.yml)" = \
  8215bb3d07f3918c6a3ecd9f92e152538625691a
test ! -e .github/workflows/dea-evidence-producer.yml
mkdir -p .github/workflows
cp docs/dea-v02-protected-producer-smoke.proposed.yml \
  .github/workflows/dea-evidence-producer.yml
git add -- .github/workflows/dea-evidence-producer.yml
test "$(git diff --cached --name-only)" = \
  ".github/workflows/dea-evidence-producer.yml"
git diff --cached --check
git diff --cached --name-status
# Human inspects exact one-file addition before the next commands.
git commit -m "feat(dea): human-adopt reviewed signed Artifact smoke Workflow (#254)"
git push -u origin issue-254-producer-adoption
gh pr create --draft --base main --head issue-254-producer-adoption \
  --title "feat(dea): human-adopt protected signed Artifact smoke (#254)" \
  --body "Human-controlled one-file protected Workflow adoption for #254; no automated policy exception, no candidate Fitness PASS. Requires GitHub review, exact-head CI and separate human Environment approval."
```

The operator must independently confirm the `gh repo view` output matches
`HyungseonSong-plasma/chatgpt-operation` before using this recipe.
`git status --short` is for inspection, not an automatic clean-check.
If a branch/file already exists or any command fails, **do not re-run
blindly**: inspect GitHub state and reconcile the work.

This CLI recipe is an **alternative UI for the same human-owned action**,
not permission for a ChatGPT connector to push Workflow content. Actions
workflows cannot be installed from the non-privileged execution channel.

## 4. Independent acceptance after the human PR

ChatGPT may resume read-only evidence gathering and normal permitted
source/test/docs work after the human has created the PR. Acceptance:

1. Verify actual repository, protected-main SHA, exact proposed YAML
   Git blob/digest, added file content, single changed file, review state,
   GitHub Ruleset and `test` check at the current PR head.
2. Verify actual human GitHub merge event and exact deployed `main`
   revision. A green CI run alone is NOT adoption or execution.
3. Before signing, verify the job is waiting on the protected
   `dea-human-break-glass` Environment and is not executing untrusted
   candidate code. The human operator must personally approve.
4. Read actual run/job/artifact metadata and the **inner**
   `dea-evidence.zip`; verify its SHA-256 independently with
   `gh attestation verify`, including signer workflow and exact
   source/signer digest. Compare with GitHub Artifact wrapper digest
   separately.
5. If provenance or identity is missing/mismatched, report
   `HUMAN_REVIEW_REQUIRED`; never mark DEA Fitness PASS, enable A/B/C
   candidate competition or auto-promote a Champion on a smoke test.

The detailed human handoff is
`docs/dea-v02-producer-smoke-human-handoff.md` and the signed-subject
contract is `docs/dea-v02-producer-attestation-adoption.md`.

## 5. Status and rollback

`GITHUB_NATIVE_ROUTE_SELECTED`
`EXTERNAL_TRUSTED_HOST_NOT_REQUIRED`
`REVIEWED_YAML_PREPARED`
`HUMAN_WORKFLOW_PR_NOT_CREATED`
`HUMAN_DEPLOYMENT_NOT_APPROVED`
`SIGNED_SMOKE_NOT_VERIFIED`

Old PR #262 and policy PR #259 must remain unmerged; their source history
may be retained as closed/superseded proposals. Preserve the automation
Workflow-denial guard and human-only emergency authority. For a failed
or compromised smoke, disable/stop the specific Workflow using competent
GitHub authority and conduct a separate reviewed rollback PR; do not
make ChatGPT auto-delete protected files.
