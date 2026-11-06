# DEA #254 — scoped Workflow Draft PR authoring bootstrap

STATUS: PROPOSAL FOR HUMAN SECURITY/POLICY REVIEW ONLY. NO CURRENT WRITE AUTHORITY.

Owner-approved adoption review: https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/254#issuecomment-6685977537

## Goal

After one formally authorized privileged bootstrap, ChatGPT may create
a new branch, add EXACTLY the reviewed DEA Producer Workflow file, and
open a Draft PR. A human retains exclusive authority to approve protected
deployment, approve the final review, merge, or change repository policy.

Allowed target: .github/workflows/dea-evidence-producer.yml
Allowed branch: issue-254-producer-adoption
Work identity: DEA-254-PRODUCER-SMOKE
Target base: protected main at an independently verified fresh SHA
Source YAML: docs/dea-v02-protected-producer-smoke.proposed.yml
Excluded: wildcard workflows, core Samuel workflows, force merge, admin
tokens, signed release without a GitHub-human approval, A/B/C candidates.

## Why ChatGPT cannot open this Workflow PR yet

(1) automation/samuel/repository-mutation-policy.json currently has
a blanket .github/workflows/** deny and no allow entry for the file.
The policy file itself is protected from automation changes.

(2) src/chatgpt_operation/repository/mutation.py separately rejects
ALL workflow-file writes on its repository-native GitHub Actions route,
regardless of JSON allowlist. Keep that hard stop and never use an
alternate native API to circumvent it.

(3) The github-connector may need GitHub App Workflows:write permission
in addition to its ordinary Contents/PR permissions. This is not
established by repository admin: true metadata. Granting a GitHub App
permission does not clear Samuel policy, and Issue #254's approval
explicitly only permits a scoped adoption review.

## Proposed one-time human policy PR (not made by this proposal)

The competent human authority must approve a reviewed privileged PR
that applies ONLY the following file path policy delta:

- file_paths.allow: append the literal value
  .github/workflows/dea-evidence-producer.yml
- file_paths.deny: remove the pattern .github/workflows/**
- preserve all other allow/deny entries and existing branch rules
- keep the deny for .github/workflows/samuel-native-github.yml
- preserve protected policy and capability registry denials
- never replace the blanket deny with a wildcard allow

The broad deny MUST be removed when adding the narrow allow because
the current policy checks deny patterns first. Other Workflow paths
remain disallowed because they match no allow pattern.

IMPORTANT: The repository-native hardcoded workflow mutation blocker
continues to apply after this change. This is intentional and means
the Workflow PR should go ONLY through a separately authorized,
trusted external provider with an enforcing prewrite gate.

## Protected external provider prewrite gate, mandatory before any write

The human-controlled bootstrap must include a trust-boundary-enforced
prewrite gate on the real connector execution path. It must check:
1. exact repository, stable task ID, single exact new file target;
2. branch named issue-254-producer-adoption and exact current main SHA;
3. only file.create and PR.create, no updates/deletions/merge;
4. proposed bytes identical to the human-reviewed YAML source;
5. human owner policy authorization still current and independently
   verified, hard TOOL_SAFETY/REPOSITORY_POLICY denials absent;
6. Draft PR only, base main, no self-review, no protected job dispatch.

A Python function in tests or a document that is NOT enforced at the
actual connector boundary is INSUFFICIENT to authorize mutation.
Until such enforcement is deployed, the Workflow write remains denied.

## One-time GitHub App/connector permission check

Human administrator checks the GitHub connection or installs a
repository-limited GitHub App with required Contents and Workflows
permissions for editing Actions workflow files and PR creation. The
Workflows permission is not intrinsically limited to one file: Samuel
must enforce the exact file/branch/work ID in its trusted execution
boundary. Never paste access tokens or account secrets in chat.
Reauthorization may be required if permissions change.

## Once bootstrap is formally adopted

ChatGPT independently reads current base SHA, prepares the exact
reviewed file in branch issue-254-producer-adoption, and opens a Draft
PR. It then reads back the head SHA, base SHA, file patch, CI and
policy evidence. The human owner reviews and merges later.
A successful CI does not prove the workflow has ever executed.

Human review and later signed Artifact smoke execution remain separate.
The full handoff: docs/dea-v02-producer-smoke-human-handoff.md

## Evidence states

BOOTSTRAP_PROPOSED -> HUMAN_POLICY_ADOPTED (requires actual privileged
merge and trusted provider readback) -> WORKFLOW_DRAFT_CREATED ->
HUMAN_DEPLOYMENT_APPROVED -> LIVE_SMOKE_VERIFIED.

This PR creates only the first state. No AI escalation is implied.

GitHub references:
https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps
