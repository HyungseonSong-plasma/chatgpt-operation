# Samuel Single Writer — authenticated source and intake gates (v0.1)

**Status:** DRAFT qualification. This branch is stacked on Draft PR #268,
which is stacked on resume PR #266. There is no production Issue #44
mutation, incoming request auto-admission, or new privilege grant.

## Proven problem

Isolated live GitHub Issue #267 confirmed **two successful PATCH calls
against the same Issue comment and revision can lose one receipt**.
Neither GitHub Actions concurrency across unrelated groups nor the Issue
comment readback is atomic compare-and-swap. The intended safety envelope is
**one trusted writer among managed jobs**, with any external/owner token still
explicitly outside that guarantee until its privileges are removed or replaced
by a genuinely atomic authority.

## Source evidence

`.github/workflows/samuel-progress-evidence.yml` is a **new read-only
producer**, distinct from the legacy *diagnostic recovery*
`samuel-evidence-acquisition.yml` (whose artifact is NOT a work-progress
receipt). Its main-only, explicitly trusted-actor job checks out the exact
Git commit, hashes an existing bounded `docs/*.md` file, rejects changed
inputs and writes a deterministic JSON record of source byte/line/link
evidence. It uploads exactly one `progress-evidence.json` artifact under
`samuel-progress-evidence-<run_id>`. Workflow permissions are
`contents:read` and `actions:read`, with **no issue write**.

`single_writer_live.verify_github_progress_source` independently checks:

- pinned SHA matches approved main source revision, trusted repository and
  workflow path, expected owner actor, `workflow_dispatch` and main event,
  run ID/attempt, `completed/success`;
- exactly one non-expired artifact named for that run and bound to its run ID;
- authenticated ZIP bytes meet bounded size and member restrictions,
  SHA-256 matches both the request and GitHub artifact digest when supplied;
- complete manifest matches work, plan, policy, input, unit, outcome and
  detailed-result SHA-256.

These checks prove **origin and payload identity**, not scientific truth or
semantic approval. Current `source` fields come from the worker-facing
request but are independently checked against GitHub metadata and ZIP bytes.
A GitHub API client must supply the ZIP from authenticated API retrieval, not
from a comment attachment or request-supplied URL.

## Full, stable intake

`read_stable_issue_comments` reads paginated Issue comment inventories
in two full passes, stopping on invalid/missing pages, duplicate IDs,
over-limit data or intervening changes; it does not claim to acquire a
server-side lock. `qualify_next_inbox_request` reuses PR #268's strict
bounded intent parser and checks **the first unprocessed proposal** against
the authenticated source, approved gates and authoritative ResearchState,
returning only a write proposal or an explicit empty result.
It does **not** PATCH anything; the caller MUST be the exclusive bootstrap
writer and invoke existing `persist_state_write`, which will re-fetch
the precondition and verify full post-write state.

## Credential-boundary defense

`GitHubNativeTransport` now prevents `COMMENT_ISSUE` and `CLOSE_ISSUE`
from modifying Samuel Issue #44. This protects one existing native
execution path without breaking Issue modifications on unrelated tasks.
The restriction is enforced on both read-before-write and mutate paths.

**Residual privilege risk:** other repository-scoped GitHub tokens and
untrusted external connectors with `issues:write` could still PATCH any
Issue comment. GitHub App Issue permissions do not isolate one Issue number.
No credible absolute single-writer claim is possible until all actual
writers are moved behind the same execution identity or the authoritative
store is replaced by an atomic ref/commit primitive.

## Qualification and remaining production gates

Automated tests cover verified current HEAD, run owner/workflow, completed
status, run attempt, artifact ZIP and digest authenticity, tampered
manifest, missing/duplicate artifacts, complete pagination, concurrent
comment changes, exact target bytes, policy/gate mismatch, Native Issue #44
write refusal and the existing 20-producer/one-writer crash replay.

Before production enablement, require:

1. **Runtime adapter:** authenticated GitHub run/artifact/ZIP GET and paginated
   comment reads inside the actual Bootstrap *with a trusted credential*;
   no worker-provided authorization. Pair these with the writer's approved
   current main SHA and independently derived gate statuses.
2. **Durable intake:** append-only request ACK with unique request ID,
   loss-of-ACK recovery and bounded backpressure. A successful Actions
   dispatch is not a durable committed intake.
3. **Privilege isolation:** inspect every workflow with `issues:write`
   and external tokens, then actually exclude direct State comment PATCH
   capability. The Native executor guard is useful but **insufficient**.
4. **Live GitHub acceptance:** actual read-only producer run/artifact,
   20 API submissions, controlled writer interruption and collision replay
   against an isolated Issue, including verification of all 20 digests.
5. **Promotion:** exact-head CI, code/security review and explicit approval.
   Do not merge these stacked PRs or change the production schedule before
   the missing gates are satisfied.

This qualification introduces no new paid service, no new authoritative
cookie store, and no new execution permission.
