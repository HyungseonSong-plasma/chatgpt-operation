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

**Mandatory pre-provider branch-name check for all registered providers:** after
checking prior same-work safety/policy blocker history, validate the target branch
against the exact head repository's `automation/samuel/repository-mutation-policy.json`
using the shared read-only CLI (or its `require_allowed_branch` function):

```bash
PYTHONPATH=src python -m chatgpt_operation.repository.branch_preflight \
  --repository HyungseonSong-plasma/chatgpt-operation \
  --branch "$TARGET_BRANCH" \
  --policy automation/samuel/repository-mutation-policy.json
```

This applies to `GITHUB_BRANCH_CREATE`, `GITHUB_FILE_CREATE`, and
`GITHUB_FILE_UPDATE`, even when `github-connector` (first-ranked provider)
performs the write. A failed/missing preflight stops the request **before**
provider invocation. The native mutation engine additionally keeps its existing
`authorize_manifest` policy check. The preflight checks branch-name
eligibility only; it does not grant write permission or clear a previous denial.
Direct connectors must run the preflight themselves; this document alone
cannot impose GitHub server-side branch rules.

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

## Mutation blocker classification and no-fallback safety

Before retrying or switching registered providers after any failed repository mutation,
classify the **observed** blocker using the deterministic
`chatgpt_operation.repository.blocker_triage` contract and read all
durable prior blocker records for the **same trusted controller-issued work ID**. A branch rename, changed file set or alternate Git API does not create a new work identity; each attempt's paths/branch must still pass their separate policy checks.
See `docs/mutation-blocker-recovery-v1.md` for the full decision table.

- `TOOL_SAFETY` and `REPOSITORY_POLICY` are **hard denials**, not
  failed providers. Stop and escalate; do not retry the same logical write via
  Git tree/commit/ref, another API, git push or repository-native Actions.
  Do not reinterpret a denied operation by changing its route or payload.
- Ambiguous GitHub 401/403/404 means read-only access investigation, not
  proven missing token scope or globally unavailable capability.
- Stale head, CI, review and workflow-provenance failures require their own
  exact-SHA replan or validation; no speculative success or forced merge.
- Only confirmed transient errors can be retried **on the same provider**,
  with bounded attempts and all original preconditions.
- The classifier does not authorize mutation. An Issue-comment-backed
  journal, complete-read and hash-chain checks, registered-work prerequisite,
  and a configurable CommonPreWriteGate are available. Repository Mutation
  Engine, Native GitHub ExecutionKernel and Controller ExecutionGateway accept
  this gate before calling write providers or dispatching action workflows.
  Production controller workflows and external connector entrypoints are NOT all
  yet configured to enforce it, so do not infer universal
  enforcement. A missing work registration, unreadable journal, stale head or
  active blocker fails closed when the gate is installed. Migration of all
  previously observed denials is required before trusting a new journal.

**Registry exhaustion applies to genuine capability unavailability, never to
bypassing an upstream safety or owner-policy denial.** A deliberately forbidden
provider route is not a candidate to exhaust through a new execution method.
 
### Clearance states and proof requirements

Do **not** require an independent policy-officer review for every temporary
blocker. Use `blocker_resolution.evaluate_clearance` to distinguish:

- `RESOLVED_AUTOMATICALLY`: trusted, exact-head source verification of a
  fixed SHA, CI, workflow inventory/provenance, up-to-date source review,
  restored scoped target access, or recovery from a confirmed transient failure.
- `RESOLVED_BY_AUTHORITY`: *only* when the competent repository-policy or
  upstream tool-safety authority has actually changed or cleared its own rule
  and a trusted adapter has verified that fact.
- `ACTIVE` / `ESCALATED`: insufficient, unrelated, stale or untrusted proof.
- `SUPERSEDED`: reserved for a proved semantically different work intent,
  never merely a different execution provider or renamed branch. V1 does not
  automatically issue this state.

Every clearance event preserves the original denial and binds the exact
logical intent, original blocker reference, new evidence reference and
currently independently observed HEAD SHA. **Release eligibility is not
permission to write**: recheck all ordinary authorization and CI gates.
External safety-screening refusals cannot be auto-cleared by Samuel or
circumvented through an alternative tool. TrustedGitHubReadbacks can verify GitHub exact SHA and successful exact-head
Actions runs; unsupported permissions, workflow provenance, review and external
safety authority claims remain unresolved. Issue comments are not immutable,
and the journal does not currently have independent tip anchoring or globally
serialized writes. Controller workflow dispatch and direct connector entrypoints
still require audited deployment; do not claim complete enforcement.

## PR branch fast-forward (review-gated; pending protected registry adoption)

Trigger `GITHUB_BRANCH_FAST_FORWARD` is owned by this skill. The only proposed provider is `github-connector`. It is limited to existing non-default Draft PR branches, first-parent non-force fast-forward to an exact-head two-parent merge commit that preserves the original PR Git tree. See `skills/repository-mutation/branch-fast-forward-v0.1.md`. An owner policy, immutable central consumer pin, trusted blocker history and read-before/write/read-after are mandatory; absent authority means STOP.
