# Samuel Issue #44 single-writer authority: two-stage resolution

**Status: DRAFT / fail-closed.** Parent: [#269](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/269)
→ [#268](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/268)
→ [#266](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/266).
No production Issue #44 mutation, new credential, secret or workflow activation
is included here.

## Investigation: exact resources and actors

The original `<!-- samuel-controller-state -->` is a single mutable comment
on source repository Issue #44. GitHub Issue-comment PATCH has **no server-side
compare-and-swap**, as isolated API qualification #267 demonstrated.

| Existing workflow / principal | Effective workflow permission | Observed intended mutation scope | Decision |
| --- | --- | --- | --- |
| `samuel-bootstrap.yml` | `issues:write` | Issue #44 heartbeat/metadata and the single ResearchState comment; `controller persist-state` | **Only managed authority for Issue #44 ResearchState** |
| `samuel-native-github.yml` | `issues:write` | General native Issue comments / close | Keep unrelated Issue behavior; Issue #44 comment/close blocked in native runtime (#269) |
| `samuel-codeqa-foreign-cycle.yml` | `issues:write` | Source Issue **#220** review ledger, codeQA target checks | Keep #220; add independently checked raw REST Issue scope |
| `samuel-chatgpt-proposal-ingress.yml` | `issues:write` | Source Issue **#220** review ledger | Keep #220; same raw REST Issue scope |
| Other scheduled wake/watchdog/preflight | `issues:read` or none | Read Issue #44, wake Bootstrap | No state writes found in reviewed paths |
| Repository administrators / external GitHub connections | Independent permission | May PATCH any Issue comment if repository Issues-write granted | **Not yet isolated or enumerated; stronger guarantee BLOCKED** |

The native `issues:write` permission is repository-wide, not Issue-number
scoped. Eliminating it from existing Issue #220 consumers would break
separate, currently legitimate workflows.

## Stage 1: controlled operational single writer

1. **Only the mainline Samuel Bootstrap may invoke durable-state persistence.**
   The CLI now verifies GitHub environment and an independently fetched
   authenticated Actions run: repository, run ID/attempt, workflow path,
   main branch, exact SHA, event and in-progress status. Incorrect claims
   hard-stop **before** any comment POST/PATCH.
2. Other Samuel raw REST source clients are restricted to **Issue #220**
   review-comment writes. A generic comment-ID PATCH first reads the live
   comment and checks its `issue_url` belongs to Issue #220. It can never
   infer the target from the comment ID alone. Native executor already
   denies Issue #44 mutations.
3. Bootstrap's existing `concurrency.group: samuel-bootstrap` (and
   `cancel-in-progress:false`, proposed `queue:max`) serializes **managed**
   state writes; worker results must go through the separately verified
   read-only request + durable `ResearchState` interface from #268/#269.
4. Regression tests assert these boundaries, retries and negative cases.
   Repo admins, arbitrary owner PATs and unreviewed new workflow files
   remain outside the code-level protection. This is **managed writer
   exclusivity**, not a server-enforced token permission guarantee.

## Stage 2: actual token-level isolation

**GitHub does not offer an Issue-specific Issues-write permission.** As long
as Bootstrap and unrelated executors have the same repository's
`issues:write`, arbitrary direct PATCH to Issue #44 remains technically
possible. Therefore existing Issue #44 cannot be an **exclusive** mutable
state store under current repository-wide credentials.

**Preferred strong option (separate free GitHub repository as the state
authority):**

1. Create a **private, dedicated repository** for Samuel's durable state
   (name and owner to be approved before migration), with **one managed
   GitHub App installation** holding the minimal repository Contents-write
   permission in this state repository only. Do not grant that installation
   to codeQA or to all workflows. Disable issue write in the state repo;
   ordinary execution tokens have **read-only** access. Never expose the
   writer credential to arbitrary PR/job code.
2. Store `ResearchState` under a dedicated protected state ref or
   immutable versioned objects, with a **server-enforced revision/commit
   precondition**. A non-force Git ref update must be tested with competing
   branch histories before claiming atomic CAS. An actually transactional
   backend is required if the proposed primitive does not prove compare-
   and-swap behavior. Do not assume a regular GitHub Issue PATCH or
   GitHub Actions concurrency is CAS.
3. Until independent live acceptance, leave Issue #44 as the sole
   authority. Build **dual-read comparison only**, never dual-write.
   Validate snapshot identity, action queue, ledger byte integrity,
   provenance, revision and all in-flight dispatch intents.
4. With an explicit approved cutover and no pending actions, stop new
   writers, take immutable snapshot, apply transactional cutover, switch the
   consumer to the new sole authority, and monitor readback. Keep a
   rollback witness, but never silently activate Issue #44 writes again
   after a later new-state update.

**Alternative:** If creating a separate repository is undesirable, keep
Issue #44 as the operational single writer under Stage 1 while explicitly
documenting that **token-level exclusivity remains impossible** within
that repository's Issues-write permissions. This is an accepted residual
risk, not Stage 2 completion.

## External configuration and rollout gates

The available GitHub integration does not expose repository provisioning,
GitHub App creation, secret administration, or installation scope changes.
Therefore **this branch cannot and does not provision the isolation**.
Owner/operator action is required, followed by independent proof:

- List all installed GitHub Apps, Actions workflows, fine-grained PATs and
  external connected users with Issues-write on the source repo;
- prove non-writer tokens receive **403** on the *new state repository* write
  endpoint while the writer credential alone can commit under its policy;
- prove competing writers do not both succeed in overwriting the same
  revision; run **20 producers + SIGKILL + lost ACK + simultaneous write**
  on isolated state before migration;
- exact-head CI and independent security review; explicit cutover/rollback
  approval. Do not treat passing CI as semantic compatibility.

**Uncompleted gates are NOT_EVALUATED/BLOCKED, not PASS.**
