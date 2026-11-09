# Samuel Controller resume coverage — v0.1 bounded implementation

**Status:** proposed and test-gated; no new cookie store, no new write authority.
**Source owner:** Samuel. **Pilot consumer:** codeQA Issue #288 read-only
documentation reference-impact analysis. Existing cross-repository native
mutation policy [#264](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/264)
remains a separate gate.

## A. Compact, lossless progress *within* ResearchState

The existing `ResearchState` durable Issue #44 ledger already retains
`research_id`, stage, action queue, execution receipts and operation IDs.
Its encoder serializes JSON and switches to **zlib+base64** above an inline
threshold, rather than dropping details. v0.1 adds the optional
`progress_checkpoint` field to that same ledger.

A checkpoint has `work_id`, plan and policy SHA-256 identities, an ordered
`units` inventory and a compact `receipts` map keyed by **zero-based index**.
Each unit ID is stored once. Every completed unit records its input SHA-256,
`PASS` or `NOOP`, and its **entire canonical-JSON-compatible detail** plus
the detail SHA-256. The receipt is never reduced to a counter or summary.
The completion bitmap and next unit are derived from these records and do
not need separately mutable fields.

This is lossless for the **stored details**, not for information the producer
never captured. A SHA-256 digest detects accidental or unilateral corruption
but does **not** authenticate an untrusted producer or prove factual truth.
Original source, snapshot, authorization and evidence provenance must be
validated independently.

Current limits are intentional: at most 4,096 units, at most 200,000
canonical UTF-8 JSON bytes per inline detail, and the existing ledger's
compressed comment/decode bounds. A larger result **fails closed**; it is not
truncated. Immutable, independently verified Git blob references might
support larger complete details later, but they are not a v0.1 capability.

Existing ledgers without `progress_checkpoint` decode unchanged. To
prevent a rollback to older Samuel source from **silently discarding**
structured progress, the durable envelope remains **schema v4** when the
optional checkpoint is absent, but uses **schema v5** once the checkpoint
is present. Older readers that support only v4 fail closed on v5.
Updating a checkpoint increments the existing `ResearchState.revision`;
there is no separate mutable cookie or source of truth.

## B. Deterministic resume decisions

The read-only command is:

```sh
PYTHONPATH=src python3 -m chatgpt_operation.cli controller resume-progress \
  --comments issue-44-comments.json \
  --input controller-progress-input.json \
  --result controller-progress-decision.json
```

Input is an object containing `plan_sha256`, `policy_sha256`,
`live_inputs` (complete unit ID to current input SHA-256), and
`gate_states` (required gate ID to `PASS`/other). These inputs must be
collected by the caller from the authoritative, current sources; a saved
claim is not sufficient.

Decisions:

| Result | Meaning | Caller action |
| --- | --- | --- |
| `READY` | Evidence-backed completed units omitted, dependent ready units selected | Continue the approved read-only unit |
| `COMPLETE` | All units have intact successful receipts for current inputs | Report scoped completion, not semantic approval |
| `WAIT_GATES` | One or more eligible units lack a current `PASS` gate | Hold those units; independent ready units may still run |
| `REFRESH_REQUIRED` | One or more input identities changed | Recompute current inputs; invalidate affected units and transitive dependents |
| `PLAN_CHANGED` / `POLICY_CHANGED` | Governing identities differ | Stop and require an approved new plan/policy |
| `HARD_STOP` | Missing/invalid ledger, malformed inventory, tampered evidence | Do not resume from suspect state |

The evaluator returns exact numeric `completed`, `ready` and `stale`
indices. It never launches workflows or writes GitHub state.

The **production `controller run-cycle` composition root** can also be invoked
with `--progress-context <file>` on an explicit isolated read-only caller
cycle. When a valid `progress_checkpoint` exists, the root emits
`selected_work.kind=progress_resume` and an exact mechanical decision, with
no `state_write` or `execution_command`. The standard scheduled
`samuel-bootstrap.yml` does **not** provide this option; no scheduler or
automatic dispatch behavior is changed. Foreign-repository admission cannot
be combined with this optional route. To persist an
accepted unit, the controller calls `record_verified_unit()` with current
input digest and gate evidence. The method is idempotent for identical proof,
rejects competing proof for the same unit, and increments the ledger revision
for a new completion. `refresh_unit_inputs()` removes only changed units and
dependent receipts, preserving unaffected progress. This local mechanism
is **not yet wired into the existing scheduled bootstrap controller's task
selection**; explicit caller/consumer integration and a live replay are
additional acceptance gates.

**Separation of authority:** An `action_queue` dispatch must continue through
Samuel's existing `dispatch_intent → dispatch receipt → observation → terminal
artifact` lifecycle. Never treat a dispatched GitHub write as an ordinary
read-only progress receipt, and never replay a denied connector mutation via
another provider.

## C. Conflict recovery and the actual persistence limit

The existing `persist_state_write()` performs a fresh authoritative issue
comment read, a revision precondition check, one write, and readback. This
detects **sequential stale writes**, but GitHub Issue comment `PATCH` does
**not** provide atomic compare-and-swap for concurrent writers.

After a stale precondition, the caller may compute a **read-only**
`reconcile_progress_conflict(base, current, proposed)`:

- `NOOP` / `ALREADY_APPLIED`: the proposed verified data introduces no
  new receipt or is already recorded.
- `MERGE_DISJOINT_PROPOSAL`: revisions advanced, source plan/policy and the
  full ordered unit inventory match, all pre-existing proofs are unchanged,
  proposed additions do not conflict with current additions, and **every
  other ResearchState field is identical**. A candidate new revision is
  produced but **not persisted**.
- `BLOCK_*`: identity, policy, input scope, revision, previously completed
  evidence, live action/execution state or competing receipt differs.
  No automatic merge or overwrite is permitted.

Even a disjoint proposal needs **one serialized authoritative writer**,
another fresh prewrite read and normal post-write readback. GitHub Actions
`concurrency` scopes only writers sharing that group; external schedulers
or connectors may not share it. Until exclusivity is established, simultaneous
writers must not auto-reconcile. If multi-writer operation becomes mandatory,
adopt an actually atomic store/ref-update primitive before permitting
automatic conflict recovery. Readback after a race is not a substitute for CAS.

## Verification scope and missing proof

Local unit tests cover restart from verified steps, lossless compressed
round-trip, saved-state tampering, gate/policy changes, targeted invalidation,
idempotent replay, stale persistence precondition, disjoint proposal, and
conflicting/live-action refusal. Existing native executor crash/retry tests
remain independent.

**Isolated real-process integration:** `tests/test_controller_crash_restart_integration.py`
uses 40 actual tracked Samuel Python source files as deterministic read-only
work units. The first actual `controller run-cycle --progress-context`
process saves 30 complete proofs using the same Issue-comment envelope and
revision precondition logic used by production, then is terminated with
OS `SIGKILL` while working on unit 31 before its receipt is stored.
A **new interpreter process** reconstructs the checkpoint from disk and
continues only units 31–40. The test checks zero duplicate completed units,
all retained receipt bytes/digests, unchanged replay, and one-file identity
invalidation without discarding independent work.

This is a **real Controller composition-root/CLI subprocess test** and a
**simulated GitHub Issue-comment transport**, not a kill of the live scheduled
Controller or a GitHub API persistence chaos test. Promotion to live use needs
the independently authorized consumer scheduler and actual GitHub transport
validation.

## Live GitHub Issue transport and concurrency qualification (2026-11-09)

**Isolated fixture:** [Samuel Issue #267](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/267);
no `samuel` label, no admitted workload, no writes to the operational
Issue #44. The live GitHub connector performed the real GitHub Issue-comment
POST, PATCH and GET operations on one schema-v5 `ResearchState` envelope.
This is a **transport-level live-API qualification**; the GitHub connector is
not the Python `persist_state_write()` transport. That Python boundary is
tested with injected transport faults in `tests/test_state_persistence.py`.

**Observed, with a single authoritative comment:**

1. After creating the Issue comment, the client **deliberately discarded
   the successful POST response** (simulating a lost acknowledgment).
   Re-reading `/issues/267/comments` recovered exactly one comment and
   revision 1. No second POST was sent.
2. After PATCH to revision 2 with verified `scan-a` detail, its successful
   response was likewise discarded. Independent GET recovered the same
   comment ID, full detail and expected digest at revision 2.
3. A second writer planned against revision 2 while the first wrote
   `scan-b` at revision 3. Authoritative prewrite GET found revision 3;
   the stale `scan-c` proposal was **not PATCHed**. After checking the
   unchanged scope, it was rebased and serially written as revision 4,
   preserving A/B/C evidence. The prewrite check is client-side and requires
   a trusted serialized writer; GitHub does not enforce it.
4. **Deliberate two-writer race on the isolated fixture:** both writers
   PATCHed the **same comment** based on revision 4, each proposing revision
   5, with independent `scan-d` and `scan-e` receipts. **Both API
   requests were accepted.** A subsequent independent GET returned only
   A/B/C/E at revision 5: **D was lost**. This proves neither revision
   equality nor two successful HTTP results imply atomic compare-and-swap.
5. The missing D receipt was explicitly re-evaluated, merged against the
   authoritative revision 5 and **serially PATCHed** as revision 6.
   Independent GET verified exactly one comment and all five A–E receipts.
   This is an **operator-controlled recovery**, not safe automatic merge
   under simultaneous writers.

The actual API test specifically confirms the requirement for
**single-writer serialization**. A digest-based / revision-based
application CAS without a server-side atomic condition cannot eliminate
the lost-update race. The existing postwrite readback might also see a
concurrent writer's **different payload at the same revision** and
incorrectly report success. The implementation is therefore hardened to
compare the **entire reconstructed ResearchState** against the submitted
payload. Injected-transport tests cover both same-revision content
mismatch and accepted POST/PATCH with lost acknowledgments.
This mitigation catches a race visible before readback but cannot prevent
a later concurrent overwrite; no production multi-writer assurance is
claimed.

Still **not proven** by v0.1:
1. end-to-end scheduled Controller adoption of this evaluator on live GitHub state;
2. safe concurrent GitHub Issue-comment writes: live API testing **demonstrates lost updates**; server-side CAS or reliably exclusive serialization is still required;
3. very large evidence preservation outside bounded comment storage;
4. cross-repository execution authority or external provider safety;
5. factual/semantic validity of read-only analysis findings.

No production scheduler, mutation gateway, or target repository policy is
modified by this proposed contract.
