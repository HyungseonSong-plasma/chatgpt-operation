# pull-request-merge

Paul skill for bounded pull-request merge execution using Samuel's authoritative native GitHub merge path.

## Ownership

This skill does **not** implement a second merge engine. It delegates to the registered `GITHUB_PR_MERGE` capability and therefore reuses Samuel's current control plane:

- `src/chatgpt_operation/controller/runtime.py::_owned_ready_pr_plan`
- `src/chatgpt_operation/github/native_executor.py::NativeGitHubCommand`
- `src/chatgpt_operation/github/native_executor.py::execute_native_github`
- `src/chatgpt_operation/github/native_runtime.py::GitHubNativeTransport`
- `src/chatgpt_operation/controller/merge_recovery.py`

Samuel remains authoritative for merge readiness, execution, verification, and rejected-merge recovery.

## Safety contract

A merge is eligible only when Samuel's native contract verifies the exact pull request head and derives all mandatory preconditions:

- pull request is not already merged;
- `head_sha == expected_head_sha`;
- `mergeable == true`;
- CI state is `success`;
- desired postcondition is exactly `merged == true`.

Execution is read-before / write / read-after. The REST merge call includes the exact expected head SHA, so a changed pull request head fails closed instead of merging stale content.

## Capability routing

Resolve `GITHUB_PR_MERGE` through `skills/capability-registry.json`.

Provider order is authoritative:

1. `github-connector`
2. `repository-native` (`samuel-controller.yml` -> `samuel-native-github.yml`)

If the first provider cannot execute the merge, do not declare merge authority unavailable until the registered Samuel fallback has also been evaluated.

## Result semantics

Samuel's native execution result is authoritative:

- `PASS` — merge completed and read-back verified `merged == true`;
- `NOOP` — desired postcondition already held;
- `REJECTED` — exact-head, mergeability, or CI precondition no longer matched;
- `FAILED` — mutation returned but postcondition verification failed.

Rejected exact-head merges enter Samuel's existing merge-recovery path; do not silently reuse a rejected workload branch.
