# Samuel Gemini review — human-owned protected activation

**Scope:** issue #307; initial adapter merged as PR #308 at commit
6fddc205f9bbf928893ac7a6d6c5150624a72136.

**State:** PREPARATION ONLY. This document does not grant write authority or
create the privileged workflow. The Samuel mutation policy denies both
.github/workflows/** and skills/capability-registry.json. A conversational
approval is not a policy-clearance mechanism and a GitHub connector must not
circumvent an observed policy denial.

**Authorized precedent:** Samuel issue #254 records the repository owner's
choice to introduce protected Workflow files with their OWN GitHub UI or
authenticated local CLI as a separately reviewed PR, not via ChatGPT's
connector, GitHub App or controller. The same human-only route is proposed
here; the competent owner must verify that this authorization still applies.

## 0. Verify owner prerequisites (no model call)

1. Owner has explicitly approved the exact change scope below.
2. The owner has inspected all files in the nonprivileged activation package
   PR and its exact-head CI is green; merge it through ordinary controls.
3. Google project quota/billing and usage limits for Gemini are configured.
   The workflow bounds one issue approval, a 90-second API call and 2048 output
   tokens, but these are NOT a financial spending limit.
4. GitHub Actions repository Secret SAMUEL_GEMINI_API_KEY exists. Verify its
   name via Settings; never expose its value to ChatGPT, an Issue, logs or PR.
5. No prior persistent mutation-policy or tool-safety denial has been cleared
   merely by this package; check the applicable durable blocker journal.

## 1. Two exactly scoped protected paths

Create, in a dedicated human-owned branch of chatgpt-operation:

A. .github/workflows/samuel-gemini-review.yml

Copy the workflow body beginning with the exact line
"name: Samuel Gemini Review" from:

    automation/gemini-review/samuel-gemini-review.proposed.yml

The proposal has pinned GitHub Actions implementation commit SHAs, an owner
Issue-label gate, explicit run_attempt=1, verified exact source input, a
credential-free preparation job, a separate Gemini-only execution job, output
receipt binding and no automatic GitHub write.

B. skills/capability-registry.json

Adopt the exact reviewed JSON contents from:

    automation/gemini-review/capability-registry.proposed.json

It preserves all eight existing capabilities and adds exactly
EXTERNAL_LLM_REVIEW -> github-issue-label-gateway, workflow-only.

Do not change automation/samuel/repository-mutation-policy.json or relax its
deny list; no other protected workflow file may change in this adoption.

## 2. Human-only authenticated CLI procedure

These commands must be reviewed and run by the human owner, not by Samuel,
ChatGPT, the GitHub connector, or automated repository mutation.

Use a local authenticated git checkout, on a clean working tree, after the
nonprivileged package has been merged to main:

    git fetch origin main
    git switch main
    git pull --ff-only origin main
    git switch -c samuel/gemini-human-activation-307

Create the workflow using the reviewed proposal body:

    mkdir -p .github/workflows
    sed -n '/^name: Samuel Gemini Review$/,$p' \
      automation/gemini-review/samuel-gemini-review.proposed.yml \
      > .github/workflows/samuel-gemini-review.yml

Copy the already-reviewed proposed registry file:

    cp automation/gemini-review/capability-registry.proposed.json \
      skills/capability-registry.json

Before pushing or opening a PR, verify exact paths and semantic contracts:

    git diff --name-only
    PYTHONPATH=src python3 -m unittest \
      discover -s tests -p 'test_gemini_activation_proposal.py' -v
    PYTHONPATH=src python3 -m chatgpt_operation.cli \
      skills validate-capabilities
    PYTHONPATH=src python3 -m unittest discover -s tests

The exact diff must contain only the two protected paths above. **Stop**
if another file is changed, the registry snapshot is stale, GitHub rules
reject the branch, or any test fails.

The human owner may then open an auditable Draft PR, e.g.:

    git add .github/workflows/samuel-gemini-review.yml \
      skills/capability-registry.json
    git commit -m "feat(samuel): owner-adopt bounded Gemini review workflow (#307)"
    git push -u origin samuel/gemini-human-activation-307
    gh pr create --draft --base main \
      --title "feat(samuel): human-owned Gemini review activation (#307)" \
      --body "Refs #307. Human-owned protected Workflow and Capability Registry adoption. No model call or automatic merge; require reviewed exact-head test gate."

The owner must review the PR and its changed-file inventory before merging.
A successful CI result is necessary but not a substitute for privileged review.
Do not use protected policy overrides, alternate Git APIs, force pushes,
bypass credentials or a consumer repo as an installation path.

## 3. Check installed exact post-state

After owner merge, verify both files exist on main, that the workflow is listed
under GitHub Actions, that EXTERNAL_LLM_REVIEW is registered and that exact-head
CI (including the required test check) succeeded. A model call is still NOT
authorized solely because these files are present.

Create the Issue Label "samuel/gemini-review-approved" in the Samuel repo
if absent. Confirm issue author/label actor matches the configured owner
and the workflow exists on main **before** applying the label.

## 4. One cheap live smoke test with explicit approval

ChatGPT may use its connected GitHub tools to create a bounded JSON review
Issue, with a publicly visible exact-SHA diff that matches the current source
PR, and explicitly ask for authorization before adding the approval label.
Only the owner-approved label event should activate a job. A second label
event or Actions rerun must never pay for another model call.

Review the Actions logs and retrieve the exact request/result Artifact:
- The prepare job must prove the current PR base, head SHA, diff SHA256 and
  full file inventory, and observe exactly one owner approval event.
- The model job must have the Gemini API secret and no GitHub API token env.
- The result must have status REVIEW_RETURNED, immutable request digest
  correlation, and merge_authorized=false.
- Retain token usage metadata; UNKNOWN, quota failure and timeouts block success.
- Re-read the target PR's latest HEAD before using the model's review.

Only after this smoke test passes should codeQA PR #300 receive an independent
Gemini review. codeQA domain authority, exact Samuel revision pins and PR merge
approval remain separate.

## Abort / rollback

Before the first live label, remove or disable the newly introduced Workflow
via an owner-reviewed rollback PR if policy/security validation fails, and
revoke the Gemini API key if exposed. Registry must not remain an enabled
provider with no executable Workflow. Preserve historical Issue/run/receipt
evidence; do not claim successful review from missing or partial artifacts.
