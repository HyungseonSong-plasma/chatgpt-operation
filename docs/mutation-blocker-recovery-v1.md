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

Before any mutation create a durable work ID and canonical desired-effect identity from repository, non-default target branch and sorted normalized target paths. The helper logical_intent_id in chatgpt_operation.repository.blocker_triage is independent of the chosen technical mechanism.

Persist source, provider, logical-intent ID, evidence reference and observed HTTP status (if any) in a nonsecret owner-accessible checkpoint. Evaluate the prior same-intent history with decide_mutation_continuation BEFORE the provider registry's fallback. A recorded tool safety or owner policy denial is monotonic across Contents API, Git tree/commit/ref endpoints, Git push and repository-native Actions. A different endpoint is not a new authorization. Resolving a hard denial requires an independently legitimate tool/owner policy decision, not a new payload or a second provider. No-blocker-record is not permission to write.

After a legitimately authorized change, verify exact head, file contents, workflow census/provenance and current-head CI. Re-review the changed SHA and run Samuel exact-head merge preflight. Never treat parser syntax evidence as public ABI, MOOSE HIT DSL or automatic rename authority.

## codeQA Issue #93 case

The earlier create_file attempt on feat/93-scoped-parser-integration-20261026 was recorded as BLOCKED BY SAFETY SCREENING; no upstream rule details are known. It is not evidence of an HTTP 403. Separately, Draft PR #153 is still 24 commits behind current main, and its 11-file source delta needs current-main workflow catalog/provenance reconciliation (23 to 24 workflows and corrected modified-workflow blob/artifact count). These are distinct issues; no attempt to re-execute the denied source-write through another endpoint is justified by this classification.

## Limits

This v1 implements deterministic taxonomy, safe-continuation checks and adversarial unit tests. It does not change external tool-safety decisions, issue GitHub credentials, automatically persist all prior blocker records, or intercept all existing dispatchers. Systemwide prevention additionally needs durable event ingestion and an enforced pre-routing hook in every write adapter, with end-to-end tests, before it can be claimed.
