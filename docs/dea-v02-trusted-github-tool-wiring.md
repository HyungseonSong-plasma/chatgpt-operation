# DEA #254 — trusted-host GitHub connector wiring and activation checklist

STATUS: INTERNAL SOURCE WIRING TESTED; EXTERNAL CHATGPT TOOL NOT DEPLOYED.
This documentation does not itself authorize Workflow mutation.

## 1. Exact intended tool boundary

Owner Issue #254 approval:
https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/254#issuecomment-6685977537

Approval is for scoped human-governed adoption review only.
The actual trusted-host entrypoint is
src/chatgpt_operation/github/dea_workflow_authoring_dispatch.py
(HostedDeaDraftService.create_review_only_draft).

It composes:
- TrustedGitHubReadbacks (exact protected main SHA);
- GitHubIssueBlockerJournal (prior denials, trusted actor);
- CommonPreWriteGate (current head, registered work, all blockers,
  independent journal checkpoint, authority-specific clearance);
- TrustedWorkflowDraftAdapter (pinned YAML -> exact branch -> Draft PR).

Allowed intended GitHub API effects only:
1. Create issue-254-producer-adoption branch at a fresh main SHA;
2. Add exactly .github/workflows/dea-evidence-producer.yml whose bytes
   match the pinned reviewed blueprint blob;
3. Open a Draft PR to main and read back all identities.

Not provided: branch deletion, workflow file update, source policy edits,
permissions escalation, merge, PR review approval, workflow dispatch,
human Environment approval, Fitness/Champion promotion.

## 2. External trusted-host configuration REQUIRED

ChatGPT's existing hosted GitHub connector is NOT implemented by this
repository's Python code. Merging this module cannot replace or hook
the existing connector's create_file action. A separately deployed
trusted integration must explicitly use this entrypoint.

Integration administrator must configure and verify all of these:

- Repository-limited GitHub App credential with required Contents,
  Workflows and Pull Requests write scopes. Never expose GitHub token
  or arbitrary transport methods to any model-facing action.
- Fixed GitHub journal Issue number and writer actor, stored in
  trusted host config, not sourced from model messages or Issue prose.
- Independently sourced historical blocker completeness proof and
  proper import/registration of this exact work ID. A clean empty
  journal is NOT proof of no historical denials.
- Separately controlled immutable checkpoint of journal sequence and
  tip, beyond the writer's permission domain. NOT another mutable
  Issue comment or ordinary unprotected repository document.
- Authority-specific verifier for any repository policy denial
  clearance; Issue comment text alone cannot clear an existing denial.
- Trusted host user/app authentication, input validation, audit logs
  and a fixed one-method model-facing tool accepting ONLY the expected
  main SHA. Reject arbitrary URL, file path, GitHub API method,
  credentials, repo, base branch, task ID, approval flags, or merge.
- Deployment of the host with exactly the reviewed source version,
  and separate registration of that protected tool in ChatGPT.

Composition signature in trusted provider code:

    service = connect_hosted_dea_workflow_authoring(
        github_transport=github_app_transport,
        host_config=HostOwnedTrustConfig(
            journal_issue_number=trusted_config.journal_issue,
            trusted_journal_actor=trusted_config.journal_writer,
            independent_checkpoint_reader=trusted_checkpoint_store.read,
            policy_authority_verifier=trusted_owner_policy_verifier,
        ),
    )
    result = service.create_review_only_draft(
        expected_main_sha=fresh_verified_main_sha,
    )

Do not run these pseudocode lines with fabricated callbacks or
user-pasted secrets. They are not a runtime deployment recipe.

## 3. Live blockers as inspected 2026-11-06

- PR #260 is merged with source regression tests.
- PR #262 contains the internal integration and remains Draft/open.
- PR #259 is open and unmerged; main policy still denies
  .github/workflows/**.
- Issue #236 is closed and has 11 comments; none currently read back
  contain the required samuel-blocker-journal-v1 marker.
- No independent immutable checkpoint provider is configured in repo.
- Current ChatGPT GitHub tool does not expose the new protected Draft
  creation entrypoint.
- No protected Workflow file has been created or signed smoke run
  executed.

Result: PRODUCTION_WRITE_NOT_AUTHORIZED.

## 4. Activation in order, never around hard denials

1. Human code reviewer validates PR #262 and merges source/tests.
2. Integration admin deploys independent journal checkpoint and
   trusted authority-verification service; migrates historical denials
   and registers the stable task.
3. Integration admin registers a new model-facing protected tool
   that delegates to this entrypoint, rather than allowing direct
   unguarded GitHub writes.
4. Prove negative production tests: no policy exception, missing
   independent checkpoint, stale main, active hard blocker, wrong
   account or changed file must produce NO GitHub writes.
5. Human reviews PR #259 after updating it to current protected
   main and confirming green CI and the real trusted-host gate.
   The new exact-file allowlist is only policy-authorized after
   formal privileged merger/readback; keep repository-native
   hardcoded Workflow-write stop intact.
6. ChatGPT may then call ONLY the protected Draft PR tool.
7. Human reviews and merges that exact Workflow PR, then personally
   approves the protected Environment to run the smoke test.
8. Signed Artifact and Attestation readbacks remain independent and
   do not imply DEA Fitness PASS.

## 5. Test meaning

tests/test_dea_workflow_authoring_dispatch.py runs an isolated fake
GitHub API and a synthetic checkpoint. Positive test exercises all
the real source components and exactly three allowed GitHub write
operations. Negative tests prove zero writes for stale SHA, policy
denial, missing work registration, active blocker and wrong checkpoint.

A fake journal checkpoint is NEVER a deployable or independently
trusted checkpoint, and passing the local CI does not demonstrate
that the ChatGPT-hosted plugin has been reconfigured.

Missing external host deployment and plugin registration cannot be
repaired by simply changing a JSON policy file or by switching to an
alternate unrestricted GitHub API route.
