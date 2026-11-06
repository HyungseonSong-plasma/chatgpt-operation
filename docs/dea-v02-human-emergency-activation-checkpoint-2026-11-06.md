# DEA human-only emergency approval — activation checkpoint (2026-11-06)

**Requested by owner:** created GitHub Environment dea-human-break-glass.
**Scope:** HyungseonSong-plasma/chatgpt-operation.
**Current status:** human environment existence is owner-reported; GitHub
environment protection rules are NOT independently attested from the
connected GitHub service. The connected reader disallows the environment
metadata URL; main branch protection GET returns HTTP 403.

## Verified live GitHub evidence

- DEA Draft PR #249 is OPEN and not merged.
- Repository rulesets endpoint currently returns **zero** rulesets.
- Samuel main repository-mutation-policy.json denies changes under
  .github/workflows/** and the policy/registry files themselves.
- No approved protected DEA Producer Workflow or human break-glass
  execution gate has been deployed.
- The human-exclusive emergency request contract and tests are present,
  but they do not grant force authority.

These observations mean ACTUAL_HUMAN_BREAK_GLASS_ACTIVATION remains BLOCKED.
The user's act of creating an Environment is not enough to run a job.

## Human-owned GitHub configuration (complete in order)

1. Settings -> Environments -> dea-human-break-glass -> Required reviewers:
   explicitly add named human GitHub user accounts (not Apps, bots or
   machine/shared logins). A single operator who starts their own run must
   leave Prevent self-review disabled; if two independent people can serve
   as requester/reviewer, enable it. Required reviewers are not equivalent
   to an independent code review on a protected PR.
2. Remove any wait timer for rapid review.
3. Turn off Allow administrators to bypass configured protection rules.
   GitHub's environment GET schema may not expose this reliably; confirm
   it directly in the GitHub UI and retain a separate authorized audit.
4. Under Deployment branches and tags, select Selected branches and tags
   and add the branch pattern **main** only (no wildcard, tag pattern or
   refs/pull/*/merge rule). This is intentionally independent of main's
   currently inaccessible branch-protection GET.
5. Settings -> Rules -> Rulesets -> New branch ruleset:
   name dea-main-protection; enforcement Active; target exactly main;
   require pull request, the verified CI context test, block force pushes
   and deletion. Protect the trusted Workflow and do not add any App/Bot
   to a bypass list. Configure independent PR reviewers separately when
   the owner has another authorized human reviewer.
6. Prepare a separately authorized, audited policy adoption to allow
   only the relevant protected Producer Workflow path; do not evade the
   current blanket .github/workflows/** denial by a connector, push or
   alternate branch. Approve and deploy the Workflow itself only through
   its normal competent GitHub/policy authority and review gates.

## Read-only verification from the owner's authenticated workstation

The GitHub-connected app in this conversation cannot read Environment
metadata, so the owner can use their existing local GitHub CLI session
(no personal access token or secret should be pasted in chat).

Run separately, using the owner-authenticated CLI session:

    gh api --method GET \
      repos/HyungseonSong-plasma/chatgpt-operation/environments/dea-human-break-glass

    gh api --method GET \
      repos/HyungseonSong-plasma/chatgpt-operation/environments/dea-human-break-glass/deployment-branch-policies?per_page=100

    gh api --method GET \
      repos/HyungseonSong-plasma/chatgpt-operation/rulesets?per_page=100

Or, with code checked out from the reviewed Samuel Draft branch:

    PYTHONPATH=src python3 -m \
      chatgpt_operation.controller.dea_environment_preflight_cli \
      --human-login YOUR_APPROVED_HUMAN_GITHUB_LOGIN

Repeat --human-login for each nominated human reviewer. This command
issues **only read-only** GitHub API GET requests, including individual
ruleset details; it does not deploy, dispatch, approve or change policies.
It emits a narrow, sanitized configuration report and never prints tokens.
Its snapshot PASS means configuration metadata agreement only, NOT
authorization. Administrator bypass status still requires UI verification.

The pure verifier in
src/chatgpt_operation/controller/dea_environment_preflight.py can also
compare independently collected GitHub REST snapshots, with negative
controls in tests/test_dea_environment_preflight.py and the CLI tests.

## Actual live activation testing — not yet performed

After an independently reviewed Producer Workflow is deployed and the
explicit Samuel workflow policy gate is legitimately cleared:

1. Trigger a bounded test job from an exact reviewed main commit.
2. Confirm its job is WAITING on dea-human-break-glass; its producer
   step must not run and no credentials become available before approval.
3. Test an unapproved/mismatched actor rejection (without generating a
   signature). A named human personally reviews the real GitHub
   deployment and approves only the exact prepared run.
4. Verify approved human and precise run/job/workflow identities from
   GitHub's live deployment review/readback. Ensure the one-time request
   has not expired or been used. A self-asserted approved=true receipt
   is not sufficient.
5. Upload and attest an actual deterministic inner dea-evidence.zip,
   retrieve the GitHub-assigned Artifact ID and digest, verify the
   certificate and subject digest with gh attestation verify, then run
   the independent codeQA Oracle. Archive the exact receipts.
6. Send any negative or missing evidence to HUMAN_REVIEW_REQUIRED;
   do not change a broken ZIP to PASS. No automatic Champion selection,
   PR merge or unreviewed policy changes.

None of the six live tests above may be marked passed on the strength of
unit tests, an Environment name alone, a synthetic signature or a green
unrelated CI run.

Official contracts:
- https://docs.github.com/en/rest/deployments/environments
- https://docs.github.com/en/rest/deployments/branch-policies
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
