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

## Permission-first diagnostic checklist (do not pre-assign a cause)

When a GitHub mutation fails, **check whether access or permissions caused it**
before investing in a new provider, workflow, executor or credential. This
check is a triage step, **not** a finding that every blocked operation is
permission-related:

1. **Record the original error:** repository, trusted work ID, requested
   operation, provider, endpoint family, exact HEAD, timestamp and the original
   status/receipt. Preserve safety-screening language verbatim; do not translate
   it into GitHub HTTP 403 without an actual GitHub HTTP response.
2. **Distinguish principals:** ChatGPT's GitHub connector may have repository
   `admin`/`push` access, while a GitHub Actions job receives its own
   `GITHUB_TOKEN`. Successful connector PR creation **does not** prove that
   Actions can create one, and enabling Actions PR creation does not change
   the connector's tool-safety decisions.
3. **For a genuine GitHub 401/403/404:** check repository and target
   existence, authenticated identity, installed GitHub App scope, token
   permissions, rulesets, protected paths and (for Actions) the workflow's
   effective `permissions:` and repository Settings → Actions → General →
   *Allow GitHub Actions to create and approve pull requests*. An observed 403
   can also mean a policy/ruleset denial. A setting change is not proof of
   access until the **specific operation** is independently read back.
4. **For external `BLOCKED BY SAFETY SCREENING`:** classify
   `TOOL_SAFETY` rather than credential failure. Stop that logical mutation.
   Settings changes, provider changes, new branches or different Git APIs
   cannot act as clearance. Request evidence from the originating safety
   mechanism; do not infer its hidden reason.
5. **For a missing action in one connector:** check the currently pinned
   capability registry and provider-specific capabilities. A provider-local
   absence is not a global capability outage; the registry does not authorize
   bypassing an observed denial. Before retrying, preserve idempotency,
   prior same-intent blocker history and current HEAD preconditions.
6. **Communicate the observed class:** report `CONFIRMED_PERMISSION_DENIAL`
   only after directly attributable access evidence, otherwise
   `ACCESS_OR_RESOURCE_UNDETERMINED`, `TOOL_SAFETY`, or `UNKNOWN`
   as appropriate. A user reporting they enabled a setting is an
   owner attestation, not independent GitHub operation-level proof.

Suggested user message for an ambiguous GitHub 403:

> GitHub reported an access or policy failure for this operation. I will first
> verify the acting identity, its scoped permissions, repository Actions
> settings (if relevant), and target ruleset; the cause is not yet confirmed.
> I will not create another execution route or retry a denied write until
> the original error is classified and the relevant permission is proven.

Suggested message for a screening block:

> The tool rejected this write at safety screening rather than returning a
> verified GitHub permission error. The cause is not established; changing
> GitHub Settings does not by itself clear the original screening refusal.

The underlying classifier in
`chatgpt_operation.repository.blocker_triage` remains authoritative. This
checklist guides evidence collection, not a new permission grant.

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

## Durable journal and common gate — implementation checkpoint

Samuel's `GitHubIssueBlockerJournal` records typed REGISTERED, BLOCKED and CLEARED events as GitHub Issue comments written by an explicitly configured trusted actor. It reads **all pages**, validates event keys, sequence and SHA-256 hash chain, retains original blocked evidence and verifies each append by an independent readback. Recording a CLEARED event is not proof that the cited clearance was authorized.

The `CommonPreWriteGate` reads this journal before a mutation, checks the exact target HEAD from a trusted reader, and revalidates **every** prior blocker with source-appropriate trusted evidence adapters. It fails closed when journal enumeration fails, the journal chain is corrupt, a blocker remains active, the HEAD differs or no trusted work registration exists. A task must be registered with its controller-issued work ID; **historical blocker migration is mandatory before enrollment**. An empty new journal is *not* proof that a previously denied task is safe.

The Samuel Repository Mutation Engine, Native GitHub ExecutionKernel and Controller ExecutionGateway workflow-dispatch boundary now provide opt-in gate hooks that refuse an active blocker **before reaching their write provider or dispatching their action workflow**. The execution kernel also refuses alternate-provider fallback on unclassified provider errors. These hooks require trusted runtime configuration and are **not automatically installed in production**. Direct external GitHub connector calls and other non-gated write routes remain outside the common gate, so do **not** call this fully deployed across all GitHub writers.

The `TrustedGitHubReadbacks` module performs actual read-only GitHub API checks for current branch SHA, exact-run/current-HEAD CI success and transient API health. Unimplemented or underspecified checks (complete workflow inventory/provenance, source-review independence, exact target write permission, owner-policy and external safety authority) return false instead of accepting model-supplied or Issue-comment evidence.

**Persistence limitations:** GitHub Issue comments survive worker/session restarts, but are not physically immutable: authorized GitHub users can edit or delete them. The hash chain detects altered or missing intermediate records but cannot, without a separately anchored expected tip, detect deletion of the entire journal or its trailing record. Nor does a read-then-write comment append provide a global atomic transaction across multiple providers. Until independently anchored checkpoints, an enforceable single-writer setup and credentials/readback are configured, treat the journal as an audited prototype rather than a hardened universal ledger.

## Independent journal-tip checkpoint — opt-in hardening

An internally valid comment hash chain **cannot detect deletion of its trailing event**. The optional `JournalCheckpoint(sequence, tip, anchor_ref)` provides an explicit external anchoring contract. `CommonPreWriteGate(trusted_checkpoint_reader=...)` independently compares the complete Issue-comment journal event count and SHA-256 chain tip with a separate trusted checkpoint. Missing, truncated, rewritten, unreconciled or unreadable checkpoints fail closed. An unrelated, non-journal Issue comment does not change the chain.

**Production trust conditions:** the checkpoint reader must be configured by a trusted runtime and return values from a storage/authority boundary **distinct from the writable Issue comments**, protected so the Issue-comment writer cannot rewrite the expected tip. A model-generated ActionPlan, PR comment, same-issue comment, unsigned local file or the Journal itself is **not** an independent anchor. Authenticate source, version, minimum prior checkpoint, and read consistency.

**Append transition:** A newly appended event is blocked until the independently controlled checkpoint has advanced to that event's verified sequence and tip. Use a single-writer/serialized process and a durable handoff receipt. There is no atomic transaction across GitHub Issues and a separate checkpoint store in this increment. On incomplete handoff, **stop** rather than guessing which state won. Never treat a matching checkpoint as work authorization; normal policy and clearances remain mandatory.

This PR provides **checkpoint verification, not provisioning or deployment** of an anchor store, privileged writer or distributed lock. Without a trusted checkpoint reader, the gate retains its existing optional/prototype behavior. Do not claim systemwide operational immutability.

## Legacy blocker reconciliation before enrollment

The `blocker_migration.reconcile_legacy_blockers` helper is a bounded, optional migration gate for **known previously blocked work**. It takes a typed, nonempty `HistoricalBlockerInventory`, an exact HEAD, a trusted completeness verifier and a configured owner Journal. It first requires an **independent source-completeness attestation**, then persists all historical `BLOCKED` records with readback and conflict checking, **then** issues one `REGISTERED` event. Existing premature registrations are explicitly rejected. Interrupted partial imports can resume without duplicate events; a journal write failure cannot advance to registration.

The source `source_ref` and `completeness_ref` strings **do not** prove historical completeness by themselves. The `trusted_inventory_verifier` must be an owner-configured integration that independently examines the authoritative historical records, work identity, and covered interval. A model-supplied callback, Issue comment, manually invented receipt, or arbitrary `True` is never deployment authorization. This helper refuses an empty inventory even if a caller asserts it is complete; genuinely new clean work requires a separate trusted enrollment process. It does **not** retrofit a mandatory check into every `journal.register_work` caller, which remains a deployment trust boundary.

**codeQA #93:** the previously denied file creation remains a historical `TOOL_SAFETY` blocker. There is no authenticated completeness adapter for that external denial source yet. Consequently **do not enroll that work through this helper** until its original evidence and scope can be verified. Even a successful migration does not clear the denial or authorize a write.

## codeQA Issue #93 case

The earlier create_file attempt on feat/93-scoped-parser-integration-20261026 was recorded as BLOCKED BY SAFETY SCREENING; no upstream rule details are known. It is not evidence of an HTTP 403. Separately, Draft PR #153 is still 24 commits behind current main, and its 11-file source delta needs current-main workflow catalog/provenance reconciliation (23 to 24 workflows and corrected modified-workflow blob/artifact count). These are distinct issues; no attempt to re-execute the denied source-write through another endpoint is justified by this classification.

## Limits

This increment implements deterministic taxonomy, typed automatic release **eligibility**, GitHub-Issue-backed journal, optional core execution gates and a bounded subset of trusted live GitHub readback validators, with adversarial tests. It does not change external tool-safety decisions, grant credentials, automatically ingest all historical blockers, enforce the gate for every production runtime or external connector, or provide an independently anchored immutable ledger. Systemwide prevention requires production configuration, controlled journal authorship, historical migration, trusted authority/provenance/review adapters, single-writer concurrency and all-route integration tests.
