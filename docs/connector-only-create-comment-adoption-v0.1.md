# Connector-only create and comment routing — protected adoption proposal

Status: PROPOSED; owner requested the four connector-only capabilities on 2026-11-25.
Base: Samuel main `972d3151527adb944f09f123a184cf791292ff36`.
Related consumer: HyungseonSong-plasma/moose-test-repo#899.

## Exact registry change

Keep schema_version=1. Apply this JSON Patch (RFC 6902) to the authoritative
registry after an authorized protected adoption. The first two operations
replace the current connector/native provider lists, the third verifies the
already-correct PR route, and the fourth registers ordinary comments.

```json
[
  {"op":"replace","path":"/capabilities/GITHUB_BRANCH_CREATE/providers","value":[{"name":"github-connector","kind":"external","priority":10}]},
  {"op":"replace","path":"/capabilities/GITHUB_FILE_CREATE/providers","value":[{"name":"github-connector","kind":"external","priority":10}]},
  {"op":"test","path":"/capabilities/GITHUB_PR_CREATE/providers","value":[{"name":"github-connector","kind":"external","priority":10}]},
  {"op":"add","path":"/capabilities/GITHUB_COMMENT_CREATE","value":{"providers":[{"name":"github-connector","kind":"external","priority":10}],"exhaustion_policy":"all_registered_providers_must_fail"}}
]
```

Require the comment key to be absent before application; re-read the exact
current registry and reconcile drift before applying any operation. All
other entries, including FILE_UPDATE, MERGE, DELETE and WORKFLOW_DISPATCH,
remain unchanged. No native, alternate API, or git fallback for the four
specified actions. A hard denial stops the same logical intent; transient
retries remain bounded and require fresh identity and original preconditions.

## Catalog and contract amendments

Add GITHUB_COMMENT_CREATE to the repository-mutation skill's load_on and
capabilities lists. Extend its README to separate create-only Connector
routing from the existing FILE_UPDATE provider chain, and define the
comment operation below. Preserve the pull-request-create contract and
ordinary prewrite policy/safety checks.

| Capability | Live Connector action | Readback |
| --- | --- | --- |
| GITHUB_BRANCH_CREATE | create_branch | Exact new branch ref and expected source SHA |
| GITHUB_FILE_CREATE | create_file | Target path/content, resulting commit and branch head |
| GITHUB_PR_CREATE | create_pull_request | Number, exact head/base, draft/state |
| GITHUB_COMMENT_CREATE | add_comment_to_issue (subject to actual action contract and target eligibility) | Target thread, new comment ID, exact body |

Discover the live Connector action/schema at execution time. For comments,
require an existing authorized Issue or PR, task/cycle/message identity,
bounded body, and complete relevant comment lookup for idempotency.
A repeated message ID with different content is a conflict. Re-read the
thread before retrying uncertain delivery. A provider's response is not
durable completion until readback. Ordinary comments do not grant authority
to change assignments, approve reviews, merge or modify/delete comments.
Separate authorization remains required for those operations.

## Acceptance tests

- All four capabilities resolve exactly one external github-connector provider.
- Missing connector evidence cannot yield an exhaustion verdict.
- Unexpected native-provider evidence is rejected for these four.
- All other provider chains equal the baseline.
- Catalog trigger and owning skill resolve GITHUB_COMMENT_CREATE.
- Existing tests expecting a native FILE_CREATE/BRANCH_CREATE fallback must
  be changed; FILE_UPDATE fallback and all unrelated tests must remain intact.
- Verify real Connector permissions and actual readbacks independently;
  a registry test does not prove live write access.
- Check execution gateway and dispatch paths for accidental native fallback,
  and test that denied attempts cannot re-enter through another route.

## Protected adoption boundary

The existing Samuel repository-mutation policy explicitly denies automated
writes to skills/capability-registry.json. This proposal does not bypass that
denial, change the policy, or activate the registry. The owner must adopt
the protected registry change through an eligible authorized route; execute
the contract and regression changes together, run CI at the exact candidate,
then merge only under separate approval. Consumer pin updates are separate
and must verify new blob identities and CI guards. Moose's existing pinned
revision will not change merely because this proposal exists.
