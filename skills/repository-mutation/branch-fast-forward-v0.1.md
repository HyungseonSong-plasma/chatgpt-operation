# Samuel `GITHUB_BRANCH_FAST_FORWARD` — proposed scoped Connector sequence

**Status:** REVIEW REQUIRED, INACTIVE (not an installed or approved capability).
**Owner:** Samuel `repository-mutation` skill.
**Provider:** existing ChatGPT GitHub Connector; no new transport.

## Scope

Allow a **non-default PR branch only**, open and Draft, with one original
commit on top of an already-squash-merged parent, where old parent Git tree
SHA equals the current target `main` Git tree SHA. The approved set of changed
paths must match the complete PR diff. No source file content changes.

This operation does *not* generalize to rebasing arbitrary histories. It is a
special merge-commit-based **fast-forward** operation. The merge commit has:

```
new_commit.tree          == original_pr_head.tree
new_commit.parents       == [original_pr_head.sha, current_main.sha]
new_commit.parent_count  == 2
```

The first parent being the existing PR head is essential: the branch update is
then a non-force fast-forward, `expected_sha=old_head, force=false`.

## Required pre-provider gates (all mandatory)

1. Resolve active consumer's exact Samuel pin; verify central catalog and
   protected capability registry from that exact SHA.
2. Registry explicitly registers `GITHUB_BRANCH_FAST_FORWARD` and lists
   `github-connector` as a supported provider. The existence of connector
   `update_ref` alone is not registration.
3. Resolve trusted, controller-issued durable work ID; read complete historic
   same-work blocker record. Reject active TOOL_SAFETY, REPOSITORY_POLICY,
   unverified authority, unavailable history, or any unresolved hard block.
4. Verify bound owner-reviewed target policy explicitly allows the operation,
   repository, branch, provider, file scope, source/target SHAs, force=false,
   effective write principal and rulesets. An Issue comment/model/JSON value
   is not itself proof of policy-owner authorization.
5. Fresh GitHub readbacks: PR open Draft, same-repository head, exact current
   head and original base, original HEAD has single expected parent, old
   parent/main tree SHA equality, original head tree SHA captured, exactly the
   authorized changed paths (complete enumeration), required original CI.
6. Recheck original branch ref and main ref immediately before Git object
   creation. No writes before all gates pass.

## Connector execution sequence

1. Existing `create_commit` with `tree_sha=old_head.tree`,
   `parent_sha=old_head.sha`, `additional_parent_shas=[current_main.sha]`.
2. Read-back created commit, require exact ordered parents and exact tree.
3. Re-read PR, old branch ref and main ref. Reject any drift; do not force.
4. Existing `update_ref` with `sha=new_commit.sha`,
   `expected_sha=old_head.sha`, `force=false`.
5. Read-back exact branch head and new commit parents/tree. On unknown result,
   do not retry a mutation blindly; perform read-only recovery.

## Downstream gates, not automatic side effects

- PR #300 still points to its original base until *separately governed* PR
  metadata update retargets it to `main`.
- Recheck complete PR diff (9 approved docs), fresh CI bound to the new head,
  review status and exact PR head before `GITHUB_PR_MERGE` (existing capability).
- Do not reuse CI success from the old HEAD.
- Keep Samuel #264 / PR #265 HOLD unchanged.

## Non-goals and restrictions

- No service/connector plugin modification; the caller must voluntarily use
  this sequence. A Skill file does not intercept other raw Connector calls.
- No force push, force-with-lease, ref rewriting, tree content change,
  arbitrary conflict resolution, or protected default-branch update.
- No self-modification of privileged Samuel registry/policy. Adoption must
  follow independently authorized review and consumer pin update.
- No assumption that GitHub account `push` permission proves target ruleset
  eligibility or external tool screening approval.
- No assertion that a `CLEAR` string is trusted unless a verified adapter
  established the identity and completeness of its backing record.
