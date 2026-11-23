# GitHub Issue Metadata Mutation — Samuel capability adoption proposal v0.1

**Status:** PROPOSAL_ONLY / NOT_REGISTERED / NO_LIVE_ISSUE_WRITES
**Consumer:** `HyungseonSong-plasma/moose-test-repo`
**Consumer Samuel pin at request:** `9b335e3fbb9c5e8e323e382daeec56fa25336822`
**Proposal baseline:** `chatgpt-operation@972d3151527adb944f09f123a184cf791292ff36`

## Problem and exact current limitation

The consumer wants to triage legacy `refactor` issues and perform narrowly authorized administrative handoffs. At its pinned revision, `skills/catalog.json` and `skills/capability-registry.json` do not register an Issue state/label mutation route. Repository-mutation v1 supports file/branch actions only; issue operations must fail closed until an explicit capability is adopted.

A GitHub connector has `fetch_issue`, `update_issue`, and `remove_issue_label`, but provider availability is not mutation authority. No Issue state or label changes occurred while preparing this proposal.

The Samuel repository's current `automation/samuel/repository-mutation-policy.json` specifically denies ordinary automated writes to `skills/capability-registry.json`. **Do not edit that path through a connector, alternate Git API, native workflow, or other route to evade the denial.** Protected registry adoption requires separately reviewed privileged owner authorization and route. This proposal changes no protected registry, workflow, policy, or production code.

## Proposed capability scope (subject to owner review)

- `GITHUB_ISSUE_STATE_UPDATE`: one exact repository + Issue number, `open` or `closed` and explicit GitHub `state_reason`; administrative closure `not_planned` must never be represented as technical completion.
- `GITHUB_ISSUE_LABEL_UPDATE`: add/remove named labels while preserving the rest; no unattended bulk sweep, no automation-triggering labels as incidental changes.
- Owner skill `issue-metadata-mutation` should be trigger-loaded, never activated merely by `INIT`.
- Candidate provider: `github-connector` only, priority 10, until another provider has an independently qualified exact-identity/check contract. Do not infer a native fallback from existing controller Issue-comment permissions.
- Registry changes and catalog/skill additions are proposed only; they **are not effective** before authorized protected adoption and tests.

## Mandatory mutation contract

1. Verify the consumer's **current exact Samuel pin**; resolve owning skill, capability and ordered providers *before* provider invocation. Reject unbound routes.
2. Resolve consumer-specific issue policy/authorization, current issue identity, state, labels, latest canonical body and dependencies. Distinguish Issue from PR.
3. Require a bounded, user-approved semantic intent: metadata closure or label cleanup, exact number, target state, rationale, preserved blockers. Do not substitute code/physics acceptance.
4. Before each write, fresh-read the exact issue and any decision-critical dependent issue. Reject unexpected state/body/labels or replan; never silently overwrite concurrent changes.
5. For `state=closed`, record the handoff to surviving owner issues, retain unresolved gates and provenance. Use `not_planned` for superseded *tracking only*, not `completed`.
6. Preserve unrelated labels; for a removal use a narrow per-label operation or an exact, freshly-read full-label set with immediate conflict checks.
7. Verify after write: exact repository/number, requested state/reason or label delta, other labels unchanged, dependent issues unaffected. A provider's success receipt alone is insufficient.
8. Hard-stop on unauthorized, policy-denied, ambiguous or stale writes. Do not use another route to bypass a safety denial. Capability-unavailable verdicts follow Samuel registry exhaustion rules.

## First consumer qualification case (no execution in this PR)

Current `moose-test-repo` candidates, as evaluated 2026-11-23:

| Issue | Proposed disposition | Mandatory caveat |
|---|---|---|
| [#157](https://github.com/HyungseonSong-plasma/moose-test-repo/issues/157) | Potential administrative `closed/not_planned` after explicit responsibility handoff | The controller's original exit criteria are **not** fulfilled. #281/#282/#283 and external SOL #172 / Adapter #29 retain actual work. |
| [#283](https://github.com/HyungseonSong-plasma/moose-test-repo/issues/283) | Keep open until explicit owner transfer or retirement | Local `physics_harness/adapters/moose` modules still exist; no zero-caller proof. |
| [#281](https://github.com/HyungseonSong-plasma/moose-test-repo/issues/281) | Keep open | Consumer callable parity and cutover not established. |
| [#282](https://github.com/HyungseonSong-plasma/moose-test-repo/issues/282) | Keep open; consider removing misclassified `refactor` label | Scientific / canonical coverage and native V&V are not accepted. |
| [#402](https://github.com/HyungseonSong-plasma/moose-test-repo/issues/402) | Keep open; consider removing `refactor` label | SCIENCE_HOLD and native-free cutover remain unresolved. |
| [#653](https://github.com/HyungseonSong-plasma/moose-test-repo/issues/653) | Keep open; consider removing `refactor` label | RF/Maxwell connectivity research only; no approved implementation. |

The final #157 handoff must not erase #283's explicit terminal ownership inventory, canonical-caller-zero proof, pinned parity, preserved historical evidence, per-module exact-head regression and no-hidden-fallback gates. The consumer's current issue bodies are canonical; verify their status again at execution time.

## Adoption and independent verification gates

1. Obtain designated Samuel owner review for both the proposed skill contract and protected registry change, including policy implications. Use an authorized privileged route; this Draft does not grant permission.
2. Add catalog trigger/skill, registry capability entries and provider checks in a separately authorized reviewed change. Include negative tests for unbound, stale and wrong-Issue operations, label preservation, `state_reason` fidelity, idempotent readback, denial/no-bypass and no false `completed` claim.
3. Confirm exact-head CI and independently review permissions / possible automation side effects.
4. Explicitly adopt the resulting **immutable** Samuel revision in `moose-test-repo` in a separate reviewed change; verify all required pinned blobs.
5. Only then perform the approved individual Issue mutations with fresh prewrite reads and post-write verification.

**Exit criterion of this proposal:** a reviewed, actionable design and honest protected-adoption gate. **Not** central capability activation, consumer pin upgrade, Issue closure, or any Physics scientific acceptance.
