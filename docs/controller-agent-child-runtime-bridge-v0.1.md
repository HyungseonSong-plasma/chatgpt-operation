# Samuel Agent Child runtime bridge v0.1 — staged integration

**Status: DRAFT, NOT ACTIVATED.** Stacked on [Draft PR #273](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/273), which depends only on crash/resume [Draft PR #266](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/266). No production Issue #44 state comment, registered Child Issue, schedule, security credential, policy or PR merger is changed by this branch.

## Ownership model

**Legacy Issue #44 is the CLOSED global Samuel Controller state Issue**;
it is NOT an eligible work parent and must not receive new Child links or
allocation comments. Instead, each separately admitted, **open** work Issue
(with `samuel` label and `work_id=issue:<parent_number>`) is the Parent
for its own agent tasks. The global Bootstrap remains the sole final
integration and authoritative `ResearchState` writer; it must not be
modified by worker dispatches.

Each Agent receives one **independent** task-parent-approved Child Issue with
immutable work ID, plan/policy SHA-256, exact source commit and bounded unit
inventory. Agents **append** completed-unit evidence comments to their own
Child only. Their working progress does **not** require any shared parent
state PATCH. The parent independently re-fetches completed proofs and
returns review-only status.

## Durable Child creation and native GitHub Sub-issue relation

`agent_issue_provision.py` provides `plan_next_child_provision`, a **read-only**
single-operation planner intended to run only under the serialized Bootstrap
writer. Its output sequence is:

1. `CREATE_CHILD`: POST GitHub Issue with deterministic provisional
   allocation fingerprint and **no `samuel` label**.
2. `FINALIZE_CHILD`: after GitHub assigns the Issue number, one-time
   PATCH of that **Child's** body with the final ownership assignment.
3. `LINK_CHILD`: POST `/issues/{parent_number}/sub_issues` with the
   **internal `sub_issue_id`**, re-enumerating the official native relation.
4. `RECORD_PARENT_ASSIGNMENT`: append an immutable allocation comment
   to the **open work Parent Issue**. Never touch the global #44
   `ResearchState` comment, parent body or any existing receipt.
5. `READY`: ownership, source, native link and parent record agree.

After any lost acknowledgement or crash, the **exclusive parent Bootstrap**
must re-enumerate all Issues, the live native Sub-issue graph and complete
parent allocation comments. Duplicate provision fingerprints and conflicting
agent assignments fail closed. `read_live_parent_registry` returns the
verified immutable parent registry only after re-reading actual Child Issue
identities and official links; its caller cannot trust a worker's claimed
registry.

**Important:** the code currently returns proposed REST steps, it does
**not** automatically execute the provisioning workflow. A real Bootstrap
adapter must bind a trusted parent plan and capture a durable create intent
*before* a POST. A GitHub Issue list is not a strong transactional creation
oracle; if a POST ACK is lost and list consistency is uncertain, **do not
blindly repeat CREATE_CHILD**. This must be verified in a live sandbox.
The Stage 2 GitHub App/atomic state-repository option is not required merely
to keep Agent-specific receipts independent.

## One independent read-only document producer per Child

`agent_issue_source.py` builds a content-addressed, exact-HEAD Markdown
reference inventory. The pilot supports only `docs/*.md` under an approved
input SHA and pinned reviewed main commit, not arbitrary repository mutation.

`.github/workflows/samuel-agent-child-evidence.yml` has a **manual
workflow_dispatch only** with a Child-number concurrency group, `queue:max`,
and repository `contents:read`, `actions:read`, `issues:write`. It
independently fetches its GitHub Actions run identity, the trusted parent's
registered Child, actual native Sub-issue relation, work units and exact
source SHA. It uploads an immutable `agent-receipt.json` as a distinct
`samuel-agent-child-evidence-<run_id>` ZIP artifact, and **POSTs only** to
`/issues/<allocated_child>/comments`, never PATCHes existing comments.
The POST path uses the Child-only `plan_child_append` contract and a full
two-pass stable comment inventory; a lost ACK triggers readback, not
an unverified second POST.

The owner actor and mainline workflow origin are hard-pinned for this pilot.
This is a controlled application-level ownership gate, **not** an Issue
number-specific GitHub permission. A repository-scoped Issues-write token
could still bypass these checks via a different script.

## Parent is a read-only verifier, not an automatic judge

`agent_issue_attestation.py` re-fetches original GitHub Actions run metadata
and the unique unexpired artifact for each Child's source run. It checks the
trusted actor, repo, workflow path, event, main HEAD, run attempt, successful
completion, ZIP checksum and exact receipt bytes before producing a trusted
input for `reduce_child_progress`.

`agent_issue_artifact_download.py` obtains GitHub's temporary signed ZIP
redirect through an authenticated **api.github.com** call, and downloads
from trusted GitHub Actions blob/CDN domains in a separate request
**without forwarding any bearer token**. ZIP bytes and limits are
independently verified by `agent_issue_attestation.py`.

`.github/workflows/samuel-agent-child-parent-audit.yml` is separate,
manually dispatched with an explicit open work `parent_issue` input (not
#44), and explicitly `issues:read`, `actions:read`,
`contents:read`. The task Parent reviews all Child Issues and their original
comments using `read_live_parent_registry` and
`reduce_verified_parent_children`. Its outputs are:
`NO_ALLOCATIONS`, `WAIT_CHILDREN`, `BLOCKED` or
`READY_FOR_PARENT_REVIEW`. None grant PR merge or state mutation.
The semantic policy approval and final parent `ResearchState` transition
remain **separate blocked production gates**.

## Important limitations

- The parent allocation is append-only rather than another shared
  PATCH target; **only Bootstrap may append it in normal operation**.
  Other workflows' GitHub `issues:write` is repository-wide. A
  malicious/out-of-band credential may still forge parent comments; token
  exclusivity is not proven by this design.
- The read-only parent runner **must not** merge a PR, promote policy,
  or mark source analysis semantics PASS solely because the ZIP/CI succeeds.
- The author identity `github-actions[bot]` is shared across Actions
  workflows; the parent run and artifact must also be independently
  attested. Stronger actor attribution for allocation comments remains a
  future security gate.
- A child may edit its own body once while provisioning; thereafter its
  immutable receipt comments must have matching creation/update times.
  The parent is not modified during the worker run.
- The GitHub connector does not expose direct native Sub-issue attach
  POST, but an isolated GitHub Actions qualification **has** exercised the
  native GitHub REST API: sandbox Parent
  [#278](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/278)
  linked actual Children
  [#279](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/279)
  and [#280](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/280).
  [Live run 42622488643](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42622488643)
  and [replay run 42622654426](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42622654426)
  passed. The replay did not create additional links. This only qualifies
  two isolated native links and an idempotent replay; it **does not**
  qualify 20 live agents, lost-create-ACK/SIGKILL recovery, or production
  admission. The earlier #274–#276 test was limited to isolated comment
  POST preservation.
- Unapproved concurrency between agents touching the same branch,
  file, PR or external resource must still fail closed. This scheme
  isolates **per-Agent progress**, not arbitrary code writes.


## Scoped work-selection preview for Issue #281 (Draft, not wired)

The dedicated technical task Parent is
[Issue #281](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/281).
It was created **without** the `samuel` label and is not yet an admitted
work item. Existing global Controller state stays on **closed Issue #255**
with an escalated predispatch failure; open Issue #256 remains
`samuel`-labelled and durably `admitted`.

`scoped_work_gate.py` performs a **read-only, complete-inventory, exact-HEAD**
preflight against the server-derived open Issue snapshot, the single
Admission ledger, and the existing global ResearchState. It blocks a
missing/unlabelled or forged Parent, conflicting open `samuel` Issues,
competing nonterminal Admission entries, mismatched active State owner,
malformed or incomplete snapshots, and ambiguous ledger comments.
`SamuelController.run_cycle(requested_work_id=...)` exercises the guard
**before** any admission/recovery/dispatch planning and returns either
`blocked_scope` or `scoped_preview`. Both return no Admission write,
ResearchState write, execution command, or Issue planning proposal.

**This is explicitly non-operational**. A `scoped_preview` result
is a snapshot candidate, not dispatch authorization. Production
`samuel-bootstrap.yml` currently has no authenticated work-ID
`workflow_dispatch` input; no runtime path sets `requested_work_id`.
An unscoped Bootstrap still uses legacy work selection and must **not**
be woken by the dedicated #281 scheduler. Extending the real Bootstrap
contract, proving freshness against schedule/dispatch races, clearing
the existing #255 and #256 ownership gates through their own authorities,
and activating the new path each require separate review/approval.
No existing global ResearchState or Issue Admission ledger was changed.


## Repository-owned scoped wake binding (next Draft gate; no production activation)

The repository-owned candidate scope is checked in at
\`automation/samuel/agent-child-scoped-preview-281.json\` with
\`work_id=issue:281\`, \`mode=preview_only\`, and **\`enabled=false\`**.
It is neither a new scheduler nor an authorization to admit #281.

\`scoped_wake_binding.py\` accepts **no externally selected work ID**.
It reads the candidate only from the checked-out repository-owned scope and
requires a native authenticated GitHub Actions run readback matching the
canonical \`samuel-bootstrap.yml\` path, \`workflow_dispatch\` event, actual
repository, \`main\` ref, exact observed HEAD, in-flight run identity, and
run attempt. Invalid or stale run evidence, a disabled policy, competing
open \`samuel\` work, and existing global ResearchState ownership return
\`BLOCKED_SCOPE\`.

The optional \`SamuelController.run_cycle(scoped_repository_policy=...)\`
**always** returns either \`scoped_preview\` or \`blocked_scope\` with
\`dispatch_authorized=false\` and **no** Admission write, ResearchState
write, Issue planning, or execution command. The current production
\`samuel-bootstrap.yml\` does **not** load this preview configuration,
supply a verified native run reader or enable scoped execution. Those
connections require a separately governed workflow/activation change.
The external scheduler's contract remains canonical wake-only; it never
selects #281 itself.

Existing Issue #255's escalated ResearchState and Issue #256's admitted
queue entry are preserved. They must be resolved through their own
authorities before #281 can be exclusively admitted and worked. Neither
the independent-review waiver nor passing unit tests permits bypassing
these existing gates. Recheck the branch head and global state before
any future execution or merge authorization.

## Promotion checklist

1. Exact-head CI. The user explicitly waived the **independent technical review** gate for this bounded Draft continuation on 2026-11-09; do not imply that a review was performed. This does not waive model/security approval, required protected-branch controls, PR merge authorization or production activation.
2. Bootstrap-exclusive, durable intent/ack executor for the proposed
   CREATE/FINALIZE/LINK/REGISTER steps, with full GitHub API readback.
3. Isolated live API test: real native Sub-issue links, 20 producers,
   lost ACK before/after creation, SIGKILL, duplicate intents, forged
   authors, and same-unit conflicts.
4. Confirm in actual GitHub Actions that source ZIP redirect, digest and
   comment timestamps match the verified runtime contract.
5. Human decision on cutover from the old shared-progress checkpoint.
   Preserve all preexisting receipt and dispatch evidence, no lost work.
6. Explicit approval for merging Draft PRs #266 and #273 plus this bridge,
   and for enabling the new workflows. Until then main and Issue #44
   remain unchanged.
