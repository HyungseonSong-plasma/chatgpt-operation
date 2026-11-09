# Samuel single-state-writer pilot v0.1

**Status: QUALIFICATION ONLY — no production intake or Issue #44 mutation enabled.**
Stacked on Draft [resume PR #266](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/266).
The existing `ResearchState` GitHub Issue #44 comment remains the sole
authoritative controller state. The new request inbox is **not** a second
state authority or a new external service.

## 1. Current writer and privilege audit

Audited current Samuel main `ae3feaea1eefc02337d9749a49868c867d3054cc`:

- `.github/workflows/samuel-bootstrap.yml` owns all known invocations
  of `controller persist-state` for Issue #44, including cycle planning,
  dispatch receipt and terminal ingestion. Its workflow-level
  `concurrency.group` is `samuel-bootstrap`, `cancel-in-progress: false`.
- The Bootstrap also writes *other* Issue #44 comments such as heartbeat,
  admission and planning metadata via `gh api`; those are distinct from
  the single `<!-- samuel-controller-state -->` comment.
- `samuel-task-watchdog.yml`, `samuel-worker-completion-wake.yml` and
  `samuel-reasoning-wake.yml` wake or observe Bootstrap and do not call
  `controller persist-state`.
- **Privilege gap:** `samuel-native-github.yml`,
  `samuel-codeqa-foreign-cycle.yml` and
  `samuel-chatgpt-proposal-ingress.yml` have `issues: write`
  for separate functions. A repository-scoped `GITHUB_TOKEN` with that
  permission cannot be narrowed to a particular Issue comment.
  External connectors may also possess independent issue-write credentials.
  Consequently the concurrency group covers managed Bootstrap runs,
  **not all possible writers to Issue #44**.

Do not label the current repo as globally single-writer guaranteed.

## 2. Existing Bootstrap as the unique managed commit boundary

The stacked branch adds `queue: max` to existing Bootstrap concurrency
to avoid cancellation/replacement of an earlier pending Bootstrap run.
GitHub.com allows at most **100 pending runs per concurrency group**; a full
queue can reject work and ordering must not be treated as a durable ledger.
The sender must retry until an authoritative accepted intake receipt is
visible. <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency>

**No new dispatch trigger, worker permission or write entrypoint is enabled
by this Draft PR.** The actual production bootstrapping, source branch and
Issue #44 comments are unchanged.

## 3. Bounded request proposal and existing-Issue inbox

`single_writer_pilot.py` defines a strict, deterministic
`samuel-state-write-intent-v1` comment envelope:

- schema, content-derived `request_id` and immutable `work_id`;
- original state revision and approved plan/policy SHA-256;
- one read-only progress unit, pinned input SHA-256, PASS/NOOP, complete
  canonical JSON details and detail digest;
- source GitHub repository, workflow name, run ID, source head SHA and
  artifact SHA-256.

A worker's request is **never** a success receipt or a mutation capability.
The theoretical durable intake path is:

1. Authorized producer dispatches a **bounded** input to the mainline
   Bootstrap; producer keeps a retryable local work cookie.
2. Bootstrap reads the source run and artifact independently and admits
   the bounded request as an append-only Issue #44 inbox comment with the
   deterministic request ID. Only **after exact readback** is intake
   acknowledged. A lost acknowledgment requires query-by-ID, not
   unconditional re-post.
3. Bootstrap serially enumerates **all pages** of inbox comments, validates
   author and request identity, re-fetches source run and artifact evidence,
   independently checks result identity and required gates, and computes
   an `state_write_request` against the latest `ResearchState`.
4. Bootstrap alone executes `persist_state_write` and verifies the entire
   post-write state. Reprocessing the same request is a NOOP; an incompatible
   result, changed policy or source head must BLOCK.
5. Requests remain available as immutable historical comments until the
   confirmed durable state contains their receipts; then processing skips
   them. A scan interruption is replayed from the existing Issue state.

Steps **1–5 describe the required future live wiring**.
The current implementation covers **request format, intake parsing and
read-only write planning only**; it does not automatically query GitHub
run artifacts, post inbox comments or PATCH the real ledger. Source
verification is a required injected *trusted* callback. CI uses an explicit
mock; no worker-supplied JSON is accepted as verification.

The simulation uses the same `state_write_request` and
`persist_state_write` contract as Samuel, with an Issue-shaped local
transport. This avoids a second cookie store or another paid service.

## 4. Collision and restart policy

- **Exclusive managed writer:** one Bootstrap group serially writes one
  unit per revision, always reading latest state.
- **Idempotent retry:** existing identical verified unit produces
  `ALREADY_APPLIED` and no PATCH, including after a lost HTTP ACK.
- **Disjoint stale request:** allowed only if same work/plan/policy,
  trusted immutable input identity and verified source; rebased onto the
  latest ledger by the exclusive writer.
- **Conflicting unit/evidence, missing gate or in-flight action:** fail
  closed; do not merge or retry across providers.
- **Crash after a committed write:** on restart read the ledger and
  intake comments; skip already completed units.
- **Unexpected writer:** GitHub Issue-comment PATCH has no atomic CAS.
  A rogue or independently authorized writer can still overwrite a
  successful managed write. Full post-write equality detects only races
  visible at the time of readback.

The live API two-PATCH lost-update evidence is documented in
`docs/controller-resume-coverage-v0.1.md` and isolated Issue #267.

## 5. Acceptance gates before enabling production intake

**Required before opening the mainline write route:**

- Implement an independently authenticated **GitHub run and artifact
  evidence verifier**; verify workflow identity, original source SHA, full
  source result digest, run completion and consumer policy. An allowed
  comment author alone is not proof.
- Establish exhaustive, paginated, stable Issue comment enumeration,
  including overflow handling and readback after request append.
- Prove that all *managed* writers use the same Bootstrap queue;
  remove direct Issue #44 mutation capability from other workflows or
  isolate the Writer using a different properly scoped identity. Document
  any residual external owner/admin writers as outside the guarantee.
- End-to-end test the real GitHub API intake, 20 concurrent dispatches,
  SIGKILL at both intake and PATCH boundaries, and lost acknowledgment
  replays; prohibit automatic merge when evidence differs.
- Gate promotion on exact-head CI and independent technical/security review.
  Neither the source's CI success nor an Issue comment grants semantic
  approval or cross-repository mutation authority.

For truly untrusted multiple writers that cannot be excluded, move the
**authoritative state commit** to an atomic backend rather than claiming
that GitHub Issue comments provide CAS.
