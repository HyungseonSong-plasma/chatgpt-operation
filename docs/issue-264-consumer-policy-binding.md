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

**Recommended portable direction:** keep the Samuel skill and capability
registry centralized, but change the pre-provider branch/policy
resolution contract in a separately reviewed follow-up so it can
consume independently authenticated **target-specific policy evidence**,
not necessarily a JSON at one hardcoded path in every repository.
For example, a reviewed target-owner policy bundle resolved from
trusted controller configuration at an immutable version could be
supported. That bundle must bind repository identity, allowed
operations/paths/branches, exact target revision, provider, and
revocation/denial history, and remain independent of an ActionPlan
or a self-authored Issue comment. None of those alternative trusted
adapters is deployed by this PR.

Consequently, **`NATIVE_TARGET_POLICY_UNAVAILABLE` is a
provider-local fail-closed diagnosis, not global
`SAMUEL_MUTATION_UNAVAILABLE`**. When no separately verified
provider-specific authorization exists, do not write codeQA.
Registry provider resolution cannot turn an upstream policy hard-stop
into a bypass.

## Current codeQA result and necessary next step

At Issue #264 kickoff, the codeQA repository was inspected and had
**no** `automation/samuel/repository-mutation-policy.json`. This is a
known **UNSUPPORTED_CONSUMER_POLICY** state, not a failed live write.
This patch does **not** add that policy to codeQA, grant permissions,
deploy the native target mutation workflow, or modify codeQA PR #290.
A reviewed codeQA-specific policy, exact target repository binding and
target-side execution provider must be adopted separately by competent
authority before cross-repo mutations are considered.

The existing codeQA PR #290 is a **pin migration** (Phase A), not a
declaration that consumer mutation authority is ready. Do not infer
Gate 2 independent semantic approval from any of these preflight
tests.

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
