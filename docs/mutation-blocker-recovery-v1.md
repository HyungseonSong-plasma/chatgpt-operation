# Samuel repository mutation blockers: classification and recovery v1

The classification contract is read-only, grants no mutation authority, and must not override tool safety screening, repository owner policy, branch protection, review or CI.

## Root-cause classes

| Source | Evidence to collect | Correct action |
| --- | --- | --- |
| Upstream tool safety screening | Denied operation, stable logical-intent ID, provider, original receipt; exact upstream screening rule may be unknown | STOP + owner/tool-governance escalation. Never change provider, API endpoint or Git transport to obtain the same denied effect |
| Owner repository policy | Target repository, reviewed policy identity, action, path, branch and exact SHA | STOP; request separate privileged policy review; never silently widen an allowlist |
| GitHub HTTP 401/403/404 | HTTP status, endpoint family, nonsecret credential identity and target policy | STOP; read-only credential/scope/ruleset investigation; a 403 has multiple possible causes and a 404 may hide inaccessible resources |
| GitHub 409/412/422 or stale Git identity | Exact expected/current head and base SHAs, branch ancestry and diff | READ_ONLY_REPLAN; no forced ref update |
| Workflow catalog/provenance drift | Complete tracked workflow inventory, exact Git blob SHAs, artifact upload counts | REPAIR_AND_REVALIDATE on an authorized branch; preserve required checks |
| Missing or failed current-head CI | Exact source HEAD, complete runs and conclusions | REPAIR_AND_REVALIDATE; historical checks do not attest a new HEAD |
| Independent review stale | Reviewed SHA, new SHA/diff, review event | REPAIR_AND_REVALIDATE; COMMENTED is not the platform APPROVED event |
| Confirmed HTTP 429 or 5xx | Exact status, same provider, bounded attempts and prior denial history | RETRY_SAME_PROVIDER only when no safety or owner-policy denial exists; ordinary preconditions remain mandatory |
| Unknown / ambiguous transport failure | Original unmodified evidence reference | STOP; no invented GitHub permission or capability absence claim |

## Required pre-routing guard

Before any mutation **bind a controller-issued, trusted durable work ID** to the target repository. The helper logical_intent_id in chatgpt_operation.repository.blocker_triage validates branch and path inputs, but computes work identity from **repository + durable work ID**: moving the same task to another branch or file set MUST NOT erase its prior denial. Branch, exact HEAD, file path changes and desired payload are separately audited and validated against owner policy on every attempt. A self-selected new work ID is not permitted to reclassify the same denied work.

Persist source, provider, logical-intent ID, evidence reference and observed HTTP status (if any) in a nonsecret owner-accessible checkpoint. Evaluate the prior same-intent history with decide_mutation_continuation BEFORE the provider registry's fallback. A recorded tool safety or owner policy denial is monotonic across Contents API, Git tree/commit/ref endpoints, Git push and repository-native Actions. A different endpoint is not a new authorization. Technical blockers, however, are not permanent bans: independently checked repair evidence may resolve them automatically. Repository policy needs the policy owner's valid authorization; an external safety denial needs clearance from its originating safety authority (which is not necessarily a human reviewer). No-blocker-record is not permission to write.

After a legitimately authorized change, verify exact head, file contents, workflow census/provenance and current-head CI. Re-review the changed SHA and run Samuel exact-head merge preflight. Never treat parser syntax evidence as public ABI, MOOSE HIT DSL or automatic rename authority.

## Evidence-based lifecycle and automatic release (v1 contract)

A durable blocker event is **append-only**: clearing its present effect does not erase the original denial. A new verified resolution event cites the original `logical_intent_id` and `blocker_evidence_ref`, the independently observed exact target HEAD and a **new, distinct evidence reference**.

| State | Meaning / entry criteria |
| --- | --- |
| `ACTIVE` | A relevant blocker exists without independently verified remediation evidence |
| `RESOLVED_AUTOMATICALLY` | The **matching technical cause** is independently revalidated: current SHA/replan, exact-head CI, workflow Git blob provenance, current-head review, scoped GitHub permission readback, or observed transient recovery |
| `RESOLVED_BY_AUTHORITY` | The repository owner-policy amendment or the original external safety authority's explicit clearance has been independently verified; not a blanket human-review requirement |
| `SUPERSEDED` | Reserved for an independently verified *genuinely different* work intent; **never** achievable by merely changing branch, API, endpoint or provider; not automatically issued by v1 |
| `ESCALATED` | Unresolved safety/policy/unknown blocker needs an authorized decision or further diagnosis; history remains intact |

The `blocker_resolution.evaluate_clearance` contract refuses an absent verifier, wrong proof kind, changed work intent, unrelated blocker reference, stale HEAD, false verifier, thrown verifier, or unsupported failure category. Normal technical fixes need **no additional independent blocker-release reviewer**. A fresh PR review may still be necessary when the PR HEAD changed; that is review of source changes, not a standing clearance committee.

`verify_technical` and `verify_authority` are **trusted adapter contracts**, not user-set Boolean permissions. Future adapters must perform actual nonsecret readbacks, and the latter must authenticate the *responsible policy or safety authority*. No self-attested Issue comment, model instruction or fabricated review event may grant clearance.

**Important:** An eligible resolution **does not authorize a GitHub write**. The ordinary repository permissions, branch policy, capability registry, current SHA, CI, review requirements and all active blockers still apply. The original source of a tool safety denial must be respected; Samuel cannot simply declare that platform refusal lifted. The legacy `decide_mutation_continuation` still fails closed on historic hard blockers until a fully audited append-only journal and common gate consume verified resolution events. Thus the new pure contract is not universal automatic enforcement.

## codeQA Issue #93 case

The earlier create_file attempt on feat/93-scoped-parser-integration-20261026 was recorded as BLOCKED BY SAFETY SCREENING; no upstream rule details are known. It is not evidence of an HTTP 403. Separately, Draft PR #153 is still 24 commits behind current main, and its 11-file source delta needs current-main workflow catalog/provenance reconciliation (23 to 24 workflows and corrected modified-workflow blob/artifact count). These are distinct issues; no attempt to re-execute the denied source-write through another endpoint is justified by this classification.

## Limits

This v1 implements deterministic taxonomy, typed automatic release **eligibility** and adversarial unit tests. It does not change external tool-safety decisions, grant GitHub credentials, independently verify provider evidence itself, persist all prior blocker and resolution events, or intercept all existing dispatchers. Systemwide prevention requires a trusted durable journal, source-specific readback verifiers, an enforced common gate in each write adapter, and end-to-end tests.
