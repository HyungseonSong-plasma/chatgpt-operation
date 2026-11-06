# DEA #254 — human operator with scoped ChatGPT delegation

**STATUS: SOURCE CONTRACT + TESTS ONLY. NOT AN ACTIVE CHATGPT TOOL.**

The repository owner `HyungseonSong-plasma` is the human **operator**.
ChatGPT may act as a **delegated worker** for ordinary, bounded operations
only when a separately deployed trusted host independently authenticates
the owner's grant, verifies that it is current/not revoked, and reserves
its use atomically. A conversational instruction is useful scope intent;
it is **not** a GitHub-signed authority receipt.

## Roles and limits

| Role | May do | Must not do |
| --- | --- | --- |
| Human operator | Own and revoke narrow ordinary delegations; make competent owner-policy decisions; personally approve protected Environment when authorized | Treat CI or chat text as signed artifact/protected approval |
| ChatGPT delegate | Analyze, edit permitted source/test/docs, run permitted CI, prepare review packet; with a valid trusted one-use grant **and all other gates**, create the one DEA Workflow Draft PR | Self-issue/renew a grant; change protected policy, merge protected PR, exercise emergency privilege, approve protected Environment or act as an independent reviewer |
| Trusted host | Authenticate caller and real operator, read signed grant and revocation state, atomically reserve one use, enforce full pre-write policy/journal gates and report GitHub readback | Offer generic GitHub API/token access to the model, auto-approve human decisions |
| GitHub protected environment | Require actual named human deployment review for protected signing | Accept a bot, chat message or model-generated approval as that review |

**The existing human-only emergency/break-glass policy is unchanged.**
This document delegates **ordinary work**, not the ability to exercise,
transfer or renew emergency authority.

## One exact delegated effect

The only effectful delegated tool defined by this proposal is
`CREATE_REVIEW_ONLY_PRODUCER_DRAFT` with:

- repository: `HyungseonSong-plasma/chatgpt-operation`
- work ID: `DEA-254-PRODUCER-SMOKE`
- delegate service: `chatgpt-protected-dea-tool`
- target: `.github/workflows/dea-evidence-producer.yml`
- branch: `issue-254-producer-adoption`
- base: the exact current, verified protected `main` SHA
- reviewed content: pinned Git blob `8215bb3d07f3918c6a3ecd9f92e152538625691a`
- grant lifetime: at most 24 hours, non-revoked, one-use

The protected `main` policy must **already** have been changed through
a separately authorized, reviewed owner-policy route, limited to this
one Workflow file. The existing deny on `.github/workflows/**` remains
effective until that formal policy change is actually adopted. The
repository-native hard-coded Workflow-write denial remains in place.
A grant never overrides either denial, an upstream tool-safety refusal,
a failed CommonPreWriteGate or protected-branch rules.

## How the operator delegates (once a trusted host exists)

1. Review the exact intended scope and PR #262 source. Use a trusted,
   independently authenticated operator configuration channel, **not**
   a chat message or public Issue comment, to create a time-bounded grant
   identifying the exact commit and delegate service.
2. Trusted host stores the authenticated evidence and revocation status
   out of the model's control. Separately deploy an independent, protected
   atomic one-use reservation ledger; callbacks always inspect current
   signature/identity/revocation state. Do not accept a plain `approved`
   boolean, a fabricated `evidence_ref`, or a local test double.
3. Give the protected ChatGPT tool just one input:
   `expected_main_sha` (40 lowercase hex characters). All other fields,
   credentials, journal checks, owner identity and authority checks are
   fixed by trusted deployment configuration.
4. Host calls `HostedDeaDraftService.create_review_only_draft`.
   It reads exact `main` policy and reviewed blob; checks current
   CommonPreWriteGate, branch/PR existence, owner grant; atomically
   reserves the one-use grant before the first GitHub write. It then
   creates at most the dedicated branch, one exact file, one Draft PR,
   verifying commit scope and GitHub readbacks.
5. Human reviews the Draft PR and makes the separate merge decision.
   For the later signed Artifact smoke, the human **personally** approves
   the protected `dea-human-break-glass` Environment in GitHub.
   ChatGPT never clicks or impersonates that approval.

To revoke: revoke the grant in the independently controlled authority
store; the verifier must reject further calls. Once a grant is reserved,
its use is consumed even if a downstream write fails or is ambiguous.
Investigate the live branch/file/PR before explicitly authorizing any
replacement grant. Never retry blind or bypass with another GitHub route.

## Trusted service integration

`src/chatgpt_operation/controller/dea_operator_delegation.py` owns
the exact typed grant / fail-closed timing, scope and reservation logic.

`src/chatgpt_operation/github/dea_workflow_authoring_dispatch.py`
now requires these additional host-only `HostOwnedTrustConfig` fields:

- `operator_grant_reader` — retrieves authentic, scoped grant metadata
  from the independently authenticated operator authority;
- `operator_grant_verifier` — independently verifies signature,
  operator/delegate binding and live revocation/expiry;
- `operator_grant_reserver` — atomically records one-time use
  in a separately governed ledger, rejecting duplicates.

These callbacks are injected **only** by the trusted deployment, never
accepted as model inputs or GitHub Issue prose. Passing unit tests cannot
prove the existence of an independent identity provider or reservation
store. Their provisioning and actual host integration remain external
deployment work.

## Activation and independent acceptance

Current: **DELEGATION_CONTRACT_STAGED_NOT_DEPLOYED**.

- [ ] Independent technical/security review of PR #262
- [ ] Real operator-authenticated grant authority + revocation service
- [ ] Durable, independent, atomic grant-reservation ledger
- [ ] Trusted historical blocker journal migration and anchored checkpoint
- [ ] Trust-boundary host deployed with precisely reviewed source and
      restricted GitHub App permissions
- [ ] Host-facing protected ChatGPT tool registered, with no arbitrary API
- [ ] Live negative cases: forged/revoked/expired/used/wrong-SHA grant,
      denied policy, absent checkpoint, stale main and pre-existing PR
      all produce zero unauthorized GitHub writes
- [ ] Separate competent owner policy adoption of exact file PR #259
- [ ] Authorized one-shot Draft PR only; normal human review/merge and
      real protected Environment approval thereafter

No workflow execution, cryptographic attestation, Champion selection,
independent review, policy authorization or emergency approval is proven
by this delegation implementation. CI demonstrates tested source behavior
only.
