# Samuel agent-owned Child Issues v0.1 — conflict avoidance by design

**Status: DRAFT qualification; production deployment is not enabled.**
This is the selected alternative to sharing a mutable `ResearchState` comment
among multiple independent agents. Based on [resume PR #266](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/266);
prior collision investigations #268/#269/#271 are **research/defense options,
not rollout prerequisites** of this partition scheme.

## Ownership model

- **Parent controller (Issue #44):** one authoritative Samuel Bootstrap owns
  approved task allocation, policy, accepted cross-agent results and final
  human/merge gate. Only parent can advance parent `ResearchState`.
- **One Child Issue per active agent assignment:** parent creates or approves
  each Child, pins the exact agent ID, work ID, plan/policy SHA-256, source
  HEAD and ordered work units. Owner assignment is verified against a
  **trusted registry independently acquired from the parent**; a Child
  body claiming ownership is not enough.
- **Agent worker:** may **POST new immutable receipt comments only in its own
  Child**. The receipt includes deterministic content-derived identity,
  input and detail digest, work unit, run identity and outcome.
  Never PATCH a prior receipt and never write the parent state.
- **Parent reducer:** reads the complete Child Issue and comment inventories,
  independently verifies each run + evidence, validates dependency gates,
  and returns `READY_FOR_PARENT_REVIEW`, `WAIT_CHILDREN` or `BLOCKED`.
  **No automatic parent revision, dispatch, PR merge or human approval.**

Do not copy the parent's entire mutable `ResearchState` to each Child.
Only copy the **scoped immutable assignment** and its source/policy identity.
For UI discoverability, a native GitHub Sub-issue relationship may be added
by the trusted parent separately; a textual link is not sufficient for
authorization. The current qualification checks independently verified
assignment + Child Issue number/URL/body and leaves native sub-issue linking
and Parent registry persistence **unwired**.

An example, not a currently existing issue mapping:

```text
Issue #44 (parent, Bootstrap-only coordination & approvals)
  Child #301 (Agent A)   -> append-only receipts A/1, A/2...
  Child #302 (Agent B)   -> append-only receipts B/1, B/2...
  Child #303 (Agent C)   -> append-only receipts C/1, C/2...
  Parent verifier        -> read-only referenced evidence + final review
```

## Important invariants

1. **No shared mutable Child state.** Parallel POST to distinct Child Issues
   does not overwrite a shared payload; each payload is immutable.
2. **Single logical completion per agent/unit.** Identical receipt replays
   are deduplicated by digest. Different result for the same unit is a
   **hard conflict** requiring review, not last-writer-wins.
3. **POST acknowledgment loss is recoverable.** Re-read the Child first;
   exact existing receipt means NOOP; if absent, do not claim success.
   A parallel POST may create physically duplicated comments but these
   are one logical proof when identical.
4. **No cross-agent ownership.** Child `issue.number` and REST `url`
   must match the parent-approved binding and the assignment digest.
   `samuel` label is forbidden on Child Issues because the existing
   Bootstrap opt-in queue treats that label as a NEW parent work item.
   Child label should be separate (e.g. `samuel-agent`).
5. **Lossless evidence and independent verification.** Full JSON detail
   and hashes are required. A worker-supplied claimed `PASS` is not
   sufficient; reviewer must independently attest exact GitHub workflow
   run and artifact. The test suite uses an explicit source-verifier double,
   **not** a production live verifier.
6. **Parent still has one writer.** Coordination or final merge decisions
   may need a parent update, but only the single Bootstrap does it.
   Child agents never concurrently PATCH parent state.
7. **No GitHub Issue-level permission isolation.** `issues:write` remains
   repository-scoped. Child ownership is an application contract enforced by
   a trusted dispatcher and runtime guards, **not** a GitHub authorization
   boundary. Repo admins/out-of-band tools remain residual risks.
8. **Other shared resources still need safety gates.** Shared branches,
   files, PRs, artifacts and external state can still conflict. Assign
   agent-owned feature branches and validate diffs/semantic compatibility
   before accepting results.

## Qualification artifacts

- `agent_issue_partition.py`: validates parent registry, agent-to-Child
  allocation, untrusted Child body, lossless immutable receipts, independent
  source-attested progress, and pure read-only parent reduction.
- `agent_issue_append.py`: builds **Child-specific POST-only proposals**,
  exact digest replay NOOP, lost-ACK readback reconciliation and strict
  contradiction blocking. It does not send network writes.
- `agent_issue_runtime.py`: parent-controlled **trusted read-only entrypoint**,
  fetching each Child Issue directly, exhaustively paging its comment history
  in two stable passes, and checking receipt `created_at == updated_at`
  to detect later edits. It calls the unit reducer only on original records,
  rather than accepting externally submitted complete/approved summaries.
- `test_agent_issue_runtime.py`: full pagination, concurrent snapshot change,
  edited receipt, forged Child identity, unverified/failed outcome blocking.
- `test_agent_issue_partition.py`: 20 parallel agent sources with 20
  distinct Issue identities and zero shared-comment PATCHes; 3-agent
  end-to-end reduce; same-unit collision, untrusted author, cross-Issue
  forgery, missing dependency/gate, failed result, duplicate POST and
  lost acknowledgment.

## Migration / production gates (not yet approved)

- **Registry:** parent-approved durable one-agent/one-Child allocation
  catalog, with independent GitHub Sub-issue relation and immutable snapshot.
  Duplicate dispatch or orphan creation must be reconciled on restart.
- **Real worker route:** safe creation/assignment and Child-only POST under
  a dedicated workflow. Never give a Child the normal `samuel` label;
  preserve existing Issue #44 admit/wake behavior.
- **Real independent verifier:** re-fetch GitHub runs, checkout SHA and
  artifacts in parent Bootstrap; reject counterfeit success. Any merge
  remains independently approved.
- **Full GitHub API acceptance:** enumerate paginated Child comments;
  separate 20 Child Issues, parallel real POST, worker kill after accepted
  POST, replay, unauthorized/foreign Child writes, source input changes,
  and exact evidence digests.
- **Parent cutover:** ensure all preexisting in-flight dispatch state in
  Issue #44 is reconciled; never silently drop old `progress_checkpoint`
  evidence or switch parent authority mid-flight. Activate on main only
  after exact-head CI, independent review and explicit approval.

**State repository/GitHub App stage-2 security gate [#272](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/272)**
can be deferred for this *operational conflict-avoidance* design. If genuine
Issue-by-Issue token-level authorization is required later, the prior gate
remains relevant. Do not claim it is already satisfied.
