# Issue #264 — exact-revision consumer policy binding

**Status:** Implemented as a fail-closed Samuel source-level preflight.
**Deployment:** NOT adopted by a codeQA consumer; no live consumer mutation
was performed or authorized. This document is an engineering test/rollout
contract, not a human policy approval.

## Problem

Previously `ExecutionGateway._dispatch_action_plan` evaluated all
`REPOSITORY_MUTATION` requests against the **Samuel** checkout's
`automation/samuel/repository-mutation-policy.json`, even when the
requested repository was codeQA. The policy had
`repository=HyungseonSong-plasma/chatgpt-operation`. This makes an
otherwise plausible codeQA request impossible to validate correctly;
removing that check or accepting Samuel's policy would be unsafe.

## Decision: never substitute a different repository's policy

The gateway now calls
`repository.target_policy_preflight.require_target_mutation_policy`
before any `dispatch_workflow` call.

1. The *trusted* Actions transport's `repository` must be exactly the
   mutation manifest's `repository`. A dispatch through a Samuel-bound
   token cannot authorize a codeQA write simply by changing an
   ActionPlan, branch name or target API.
2. For Samuel-targeted operations, preserve the existing canonical local
   policy/branch-name check with no changes to Samuel policy bytes,
   repository-native manifest engine, capability registry, provider
   ordering or protected Workflow scope.
3. For **non-Samuel** consumer-targeted operations, require a
   target-owned, trusted Actions transport, a dispatch on `main`,
   the expected native `samuel-repository-mutation.yml` workflow, and
   an exact lowercase 40-hex SHA for the expected consumer `main`.
4. Before dispatch, read target `main` through
   `GET /git/ref/heads/main`. It must equal that exact SHA.
   Read **the consumer repository's own**
   `automation/samuel/repository-mutation-policy.json` through
   `GET /contents/...?...ref=<exact SHA>`. Require canonical file
   type/path and base64 encoding, a bounded byte size, a matching Git
   blob SHA computed from the decoded raw bytes, exact length and
   strict JSON without duplicate keys.
5. Apply the existing strict policy parser, reject if
   `policy.repository` differs from the requested consumer, and
   authorize the **complete** create/update/branch-create manifest
   with the policy's file/action/branch allow/deny sets and the existing
   hard-coded protected Workflow file prohibition.
6. Read consumer `main` SHA again after policy read. Reject if the
   repository advances during the preflight. The target native
   mutation engine, trusted work history, registered provider, CI and
   GitHub permission gates remain independently authoritative.

Consumer-missing-policy, wrong-repository transport, malformed blob,
stale ref or unavailable readback all fail **before any workflow dispatch**
with a clearly classified policy/preflight error; they must not be
reinterpreted as provider unavailability or authorization to switch to an
alternate GitHub API.

## Samuel skill vs individual execution providers

**Important distinction:** Absence of a consumer-owned
`automation/samuel/repository-mutation-policy.json` does **not**
make Samuel's reusable `repository-mutation` **skill** unavailable.
Samuel owns the skill and the trigger/capability/provider router; a
consumer binds it to an immutable Samuel revision.

The file-specific restriction implemented in this PR applies to
the `ExecutionGateway`'s **repository-native
`REPOSITORY_MUTATION` dispatch path**, not to the GitHub Connector
provider or to read-only Samuel, PR creation, CI observation, or the
independently governed branch-delete contract.

The canonical `skills/repository-mutation/README.md` currently
also specifies a **pre-provider** target branch-policy check for file
and branch creation/update (including connector). Therefore choosing
`github-connector` must **not** be used to bypass a missing target
policy or a prior owner/tool-safety denial.

**Implemented portable pre-provider contract:** keep the Samuel skill
and capability registry centralized. A consumer need not duplicate the
Samuel policy JSON in its own repository. For a separately owner-approved
and trusted enrolled consumer, the common **connector** preflight is
`repository.central_policy_preflight.require_central_connector_preflight`.
The `CentralPolicyBinding` is injected from trusted controller configuration,
not from the ActionPlan, a user-editable Issue comment, or a self-authored
policy. It fixes the exact consumer repository, target `main` SHA, protected
Samuel source `main` SHA and an expected immutable source Git blob SHA.
Two independent repository-scoped GitHub read transports verify their
current `main` revisions; the central source's fixed
`automation/consumer-policies/<owner>/<repo>.json` policy path must match
the manifest identity. It validates raw Git blob bytes, strict schema,
file/branch/action constraints and source/target repeat readbacks.

The preflight's success receipt is explicitly
`PREFLIGHT_PASSED_NOT_WRITE_AUTHORIZATION`: **no provider is executed**,
no consumer is automatically enrolled and no credentials are conferred.
The policy-owner approval and credential registration process is still a
separate, trusted operational gate, as is post-mutation readback. Only
`github-connector` is supported by this central resolver; a
`repository-native` Engine will still require its own target-local policy
independently. A prior tool safety or owner-policy denial must never be
converted into a provider-switch opportunity.

Tests `tests/test_central_policy_preflight.py` demonstrate a mock-only
successful central policy resolution and fail-closed wrong transport,
wrong identity, stale target/source revision, altered Git blob, missing
policy, malformed schema, unsafe path/operation/branch and provider
selection. None of the tests performs a GitHub write.

Consequently, **`NATIVE_TARGET_POLICY_UNAVAILABLE` is a
provider-local fail-closed diagnosis, not global
`SAMUEL_MUTATION_UNAVAILABLE`**. When no separately verified
provider-specific authorization exists, do not write codeQA.
Registry provider resolution cannot turn an upstream policy hard-stop
into a bypass.

## Current codeQA result and necessary next step

At Issue #264 kickoff, codeQA had no target-native
`automation/samuel/repository-mutation-policy.json`. Native mutation is
therefore **UNSUPPORTED_CONSUMER_POLICY** (not a live failed write).
Central connector preflight is implemented as a read-only library but no
approved codeQA central policy source, target binding, or caller-side
provider adapter has been enrolled; live connector writes remain **NOT AUTHORIZED**.
No consumer policy/credentials, native target workflow, protected
Workflow or codeQA pin are changed in this PR.

The existing codeQA PR #290 is a **pin migration** (Phase A), not a
declaration that consumer mutation authority is ready. Do not infer
Gate 2 independent semantic approval from any of these preflight
tests.

## Explicit pending adoption gates

1. A competent codeQA policy owner must review and approve a bounded
   target policy. A future central source file merged on protected Samuel
   `main` is not, by itself, evidence of that approval.
2. Trusted controller configuration must enroll its precise target,
   target revision, Samuel source revision, reviewed policy blob and
   independently verifiable owner-authority receipt.
3. The live GitHub Connector entrypoint must call the pre-provider gate
   and same-work blocker history check **before any write**, preserving
   capability registry provider order. The current GitHub plugin is not
   automatically instrumented by this Python library.
4. For real mutations, perform independent target exact-SHA read-before,
   GitHub permission/ruleset checks and read-after postconditions.
5. Preserve `NATIVE_TARGET_POLICY_UNAVAILABLE` for consumer-native
   workflows until the target runtime has its own authorized policy.

## Tests and criteria

`tests/test_target_policy_preflight.py` covers mock, read-only:

- Samuel allowed/denied branches retain their prior behavior.
- Exact target policy from a repository-scoped transport passes a
  bounded fake dry-run; file create/update and branch creation checked.
- Wrong-target transport, missing consumer policy, stale/malformed
  expected revision, mid-read `main` update, repository mismatch,
  changed/forged Git blob SHA, byte size, malformed/duplicate JSON,
  unsupported file paths, unsupported actions and branch denial all
  reject **before** a real dispatch.
- Gateway-level negative tests ensure no dispatch under mismatched or
  missing policy. Positive gateway test mocks `dispatch_workflow`;
  no GitHub mutation occurs.

CI tests are not a substitute for operating authorization or a live
consumer smoke run. Record the exact PR HEAD and passing CI run as
the *source-level* evidence only. For codeQA, the supported outcome
today is an explicit fail-closed policy verdict.

## Non-goals

No changes to `.github/workflows/**`, the main branch, policy JSON,
capability registry, branch-delete semantics, connector-only PR-create
semantics, owner approvals, or consumer pin adoption.
