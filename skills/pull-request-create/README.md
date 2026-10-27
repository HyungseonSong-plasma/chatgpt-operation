# pull-request-create

Samuel trigger: `GITHUB_PR_CREATE`. This skill owns the explicit, non-merge creation of reviewable pull requests, routed through the pinned capability registry.

## Registered provider

`skills/capability-registry.json` registers two ordered create-PR providers:

1. `github-connector` (priority 10), when authorized and available.
2. `repository-native` (priority 20), using `samuel-controller.yml` and the
   trusted `samuel-native-github.yml` executor with the `github-native-dispatch`
   contract. The native executor already supports the closed-world `create_pr`
   action, and the execution kernel maps it to `GITHUB_PR_CREATE`.

Fallback is permitted only after provider-local unavailability, not after a
policy denial or an external safety-screening block. Both providers require
fresh authorization and authoritative pre/postcondition evidence. Registration
of the native provider does **not** override the protected-path deny list,
authorize registry self-modification, bypass a blocker, or grant merge authority.
Do not substitute the `GITHUB_PR_MERGE` route for PR creation.

## Preconditions

1. Resolve `GITHUB_PR_CREATE` from the exact pinned central catalog and registry **before** invoking a connector.
2. Establish the repository and target branch identities from fresh GitHub reads; require the proposed head branch to exist with a verified exact head SHA and base branch to be current.
3. Confirm there is no existing open PR for the same head/base. If one exists, reuse its identity instead of duplicating a PR.
4. Confirm the proposed changes are source-scoped, compatible with consumer-owned policies, and reviewed for secrets or unwanted writes.
5. PR creation is not semantic acceptance. Use draft PRs for unresolved human policy decisions and preserve frozen public contracts.

## Execution and verification

Invoke the ordered registered provider for `GITHUB_PR_CREATE`, then read back the new PR's number, head SHA, base SHA, draft/state, diff and required CI trigger. A changed head/base requires fresh validation. A claimed creation is valid only when a PR exists at the verified exact head.

After creation, delegate exact-head validation observation to `github-actions-observation`; do not infer CI PASS or domain acceptance from opening a PR. Merge must separately resolve `GITHUB_PR_MERGE` and satisfy `pull-request-merge` safeguards.

## Retry / uncertainty

A missing creation receipt is an external wait or recovery state, not grounds to create duplicate PRs. Re-read head/base and query existing PRs before retrying. A provider-local error is not a globally unavailable capability verdict without the registry's exhaustion process.

## Scope

No automatic source rename, schema/API/ABI migration, review approval, forced merge or branch deletion.
