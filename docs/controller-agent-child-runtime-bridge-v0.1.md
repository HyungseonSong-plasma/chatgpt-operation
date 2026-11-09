# Samuel Agent Child runtime bridge v0.1 — staged integration

**Status: DRAFT, NOT ACTIVATED.** Stacked on [Draft PR #273](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/273), which depends only on crash/resume [Draft PR #266](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/266). No production Issue #44 state comment, registered Child Issue, schedule, security credential, policy or PR merger is changed by this branch.

## Ownership model

Parent Issue #44 remains the only coordination and final-decision authority.
Each Agent receives one **independent** parent-approved Child Issue with
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
   to the Parent Issue, without editing the `ResearchState` comment.
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
manually dispatched and explicitly `issues:read`, `actions:read`,
`contents:read`. The Parent reviews all Child Issues and their original
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
- Current GitHub connector cannot issue native Sub-issue attach POST
  directly; runtime live acceptance **has not been executed**. Tests use
  a realistic GitHub REST simulator. The prior real test #274–#276
  established only inert, disjoint comment POST preservation.
- Unapproved concurrency between agents touching the same branch,
  file, PR or external resource must still fail closed. This scheme
  isolates **per-Agent progress**, not arbitrary code writes.

## Promotion checklist

1. Exact-head CI, independent technical review and model security review.
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
