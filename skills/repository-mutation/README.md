# repository-mutation

Portable deterministic repository mutation skill and the mandatory routing owner for GitHub state-changing repository operations.

## GitHub mutation routing invariant

For every GitHub state-changing repository operation, resolve the Samuel skill/capability contract **before** invoking an execution provider.

```text
mutation intent
  -> Samuel trigger/skill resolution
  -> capability registry
  -> ordered provider resolution
  -> fresh target identity check
  -> provider execution
  -> postcondition verification
```

Direct provider availability does not bypass skill resolution. A missing operation on one provider does not establish capability absence; all providers registered for the resolved capability must be evaluated according to the registry exhaustion policy.

## Supported v1

| Resource | Actions |
|---|---|
| file | create, update, delete |
| branch | create, delete |

All other resource/action pairs fail closed.

### Branch delete

`GITHUB_BRANCH_DELETE` is owned by this skill and is bound to the existing exact-SHA guarded `chatgpt_operation.repository.branch_delete:delete_branch` contract.

The delete contract requires:

- exact current branch SHA supplied as `expected_sha`;
- default branch deletion denied;
- read-before identity verification;
- delete only after the SHA lease matches;
- read-after verification that the ref is absent;
- already-absent target returns `NO_MUTATION_NEEDED`.

The execution provider is selected through `skills/capability-registry.json`; provider-specific tool absence is not a capability verdict.

## Retry semantics

Desired post-state is recognized before stale identity rejection where applicable:

- create + matching content -> `NO_MUTATION_NEEDED`
- update + matching content -> `NO_MUTATION_NEEDED`
- file delete + target absent -> `NO_MUTATION_NEEDED`
- branch create + desired head already present -> `NO_MUTATION_NEEDED`
- branch delete + target absent -> `NO_MUTATION_NEEDED`

This makes retry safe after remote success followed by local result-persistence failure.
