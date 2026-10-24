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

## Explicit file and branch creation/update capabilities

Samuel's `MUTATE` trigger selects this skill; concrete operations additionally resolve
`GITHUB_FILE_CREATE`, `GITHUB_FILE_UPDATE`, or `GITHUB_BRANCH_CREATE`
from the **exact pinned** `skills/capability-registry.json`.

Registered ordered providers are:

1. `github-connector` (external API; caller holds no GitHub token);
2. `repository-native` (`.github/workflows/samuel-repository-mutation.yml`,
   restricted by `automation/samuel/repository-mutation-policy.json`).

Before execution, re-read file blob SHA (update) or absence (create), target
branch and expected head SHA. After execution, verify created/updated content,
branch head and resulting commit; a provider's success response alone is not
postcondition proof. Repository-native policy denial is a real denial for that
provider, **not** authority to bypass it via a connector. Creation of a PR is
a separate `GITHUB_PR_CREATE` trigger owned by `pull-request-create`.

Changing the capability registry itself is a privileged OS-adoption/bootstrap
change. The repository-native policy deliberately denies this path. Such
changes must proceed by an explicitly authorized, reviewable change through
an eligible privileged execution route; no scheduler or consumer may silently
rewrite its own trusted routing authority. Pin upgrades in consumers remain
separate explicit repository changes.

## Negative capability verdict hard guard

A user-facing claim that a GitHub mutation capability is unavailable is itself a governed routing decision.

Examples include statements such as:

- `the API/action is not exposed`;
- `this tool cannot delete the branch`;
- `the operation is unsupported`;
- `no provider is available`;
- `I cannot perform this GitHub mutation`.

Before emitting such a claim, resolve the owning mutation trigger/skill and the concrete capability entry. Then evaluate every registered provider in registry order. Provider-local tool/action absence is only provider-local evidence and **must never** be promoted directly to a global capability verdict.

For capabilities whose exhaustion policy is `all_registered_providers_must_fail`, a global unavailable verdict is permitted only after calling the machine guard:

```python
from chatgpt_operation.skills.capability_registry import assert_capability_exhausted

assert_capability_exhausted(
    "GITHUB_BRANCH_DELETE",
    {
        "repository-native": "fresh failure evidence",
        "github-connector": "fresh failure evidence",
    },
)
```

If any registered provider is missing from the supplied failure evidence, the guard raises `CapabilityRegistryError` and the negative verdict is forbidden. Continue provider resolution instead.

This guard applies even when no mutation has yet executed. Capability-unavailability assertions are therefore routed through the same Samuel ownership boundary as the mutation itself.

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
