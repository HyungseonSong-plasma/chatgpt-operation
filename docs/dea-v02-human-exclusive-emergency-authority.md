# DEA Human-Exclusive Emergency Authority (Break-glass) — proposed contract

**Status: DESIGN + READ-ONLY REQUEST GUARD, NOT DEPLOYED.**
**Source:** codeQA #288 / DEA #246 / Samuel Draft PR #249.
**Owner decision (2026-11-06):** in urgent cases, force-command authority
belongs only to a real, explicitly authorized human. AI / Samuel / DEA /
scheduled controllers / GitHub Apps and service accounts cannot obtain,
delegate, renew or exercise that authority.

## 1. Separate rapid results from force authority

- FAST LANE: Controller can inspect blockers, retry known transient failures
  within current approved scope, obtain a new evidence run if the existing
  trusted workflow and policy *already permit it*, preserve invalid outputs
  and prepare a human review packet. This lane grants NO emergency privilege.
- HUMAN BREAK-GLASS: a named GitHub human account personally authorizes an
  exact one-time emergency action through a configured GitHub protected
  environment, reviewed PR or separately governed owner-only GitHub UI.
  The repository's **actual** authority layer, not a chat utterance, grants
  access. A resulting approved standard workflow may then execute within its
  normal scoped permissions. No AI-origin token may perform the human click.
- POLICY / SAFETY HARD STOP: an existing explicit repository policy denial,
  external tool-safety refusal, or branch protection is NOT overrideable merely
  by saying FORCE, adding a flag to JSON, making an issue comment, changing
  the GitHub API/branch, or using an alternative provider. The competent
  administrator must formally change/approve the governing rule via a
  separately authorized route, with audit trail, before affected work resumes.

## 2. Emergency request envelope (implemented, read-only)

Module: src/chatgpt_operation/controller/dea_human_break_glass.py.
Tests: tests/test_dea_human_break_glass.py.

A request is narrow: exact repository, exact 40-hex commit, stable work ID,
enumerated action and reason, optional Run/Artifact IDs, UTC creation/expiry,
duration at most 30 minutes, deterministic ID and one-use intent.

Only these **requests** can be prepared:
- EXPEDITE_EVIDENCE_REVIEW
- REQUEST_PROTECTED_PRODUCER_RUN
- REQUEST_WORKFLOW_POLICY_ADOPTION
- REQUEST_HUMAN_ONLY_MANUAL_RECOVERY

These are requests for human action, NOT executable capabilities. There is
no FORCE_MERGE, IGNORE_SAFETY, AUTO_ADMIN, or unbounded "override everything".
The module cannot authenticate a person from its own arguments. Even a JSON
claim of {"approved":true,"role":"owner"} always yields
EXTERNAL_HUMAN_GITHUB_GATE_REQUIRED, no mutation or promotion rights.

A natural-language chat instruction from the owner is useful task intent,
not an independently authenticated GitHub approval receipt.

## 3. Official protected GitHub adoption route (not configured)

Once the competent repository owner accepts a reviewable policy change,
configure a GitHub Environment named dea-human-break-glass:

1. Settings -> Environments -> New environment; use only named human GitHub
   accounts or a vetted human-only team as required reviewers; no bot,
   GitHub App, shared machine account, or contractor service login.
2. Restrict deployment branch/tag to a protected, reviewed source. Pin the
   workflow and verifier/action commits. Put narrowly scoped credentials
   only in the protected environment, not in candidate jobs or chat.
3. Limit the job to an immutable, verified emergency request envelope:
   exact work, repository, HEAD, allowed action, one run, short expiry.
   Enforce expiry and one-time consumption server-side under a trustworthy,
   replay-resistant audit ledger (request text is not an authorization).
4. Ensure the environment approval is a real GitHub deployment review event.
   Controller-generated comments, candidate metadata and bot actors are
   not valid human identity sources. Independently read back the approval
   and current permissions; record approver identity and GitHub audit link.
5. Disable routine admin bypass of protected environment rules when high
   assurance is required. If self-review prevention is enabled, the triggering
   human must be different from the approving human, so provide an alternate
   named reviewer and avoid designing an impossible single-person fast lane.
6. For one-person urgent evidence collection, use a *separate, low-risk*,
   human-approved bounded rerun that does NOT waive protections or grant new
   policy authority. For an actual policy exception, require the competent
   administrator and a reviewable change; don't downgrade it to a rerun.

No such environment, one-use server-side consumption, protected workflow
or independently authenticated approval adapter is deployed by this PR.
The current Samuel policy denies .github/workflows/** changes and the
central registry/policy paths; there is no alternate write route.

## 4. Operational human interaction

The Controller prepares an emergency packet containing target SHA, exact
blocking evidence, proposed bounded action, allowed time and rollback plan.
A human logs into GitHub with their own account, opens the protected job or
PR, reviews the evidence and approves/rejects in GitHub. The real GitHub
platform checks authorization. A trusted verifier records independent
GitHub event/identity/HEAD readback. If accepted and existing repository
policies allow the operation, the approved job runs under the narrow role.
After completion, read back actual run/commit/artifact/attestation; expire the
request and preserve the outcome for audit.

A human may also perform a separate authorized manual recovery in GitHub UI.
The model never impersonates the human, handles their credentials, asks for
a token, or executes the protected force click. Urgency does not make invalid
evidence true and does not transform a failed artifact into Fitness PASS.

## 5. No blanket bypass privileges

- AI / Controller: no bypass, no admin token, no protected policy edits.
- Human: only the actual platform/policy authority they already legitimately
  hold; an emergency request does not confer missing privileges.
- Github Rulesets bypass lists can include teams/roles/apps; for this design,
  the designated bypass principals must be individually controlled humans,
  not Apps/bots or generic write roles. Prefer narrowly scoped PR-only
  exceptions where possible.
- Attestation/provenance failures remain HUMAN_REVIEW_REQUIRED. A human may
  request fresh evidence but cannot assert a cryptographic signature PASS.
- Merge/champion, domain-semantic contracts, tool safety and independent
  reviewer obligations retain their own gates.

## 6. Current admission state

REQUEST_GUARD_TESTED, HUMAN_GITHUB_GATE_NOT_CONFIGURED,
POLICY_EXCEPTION_NOT_GRANTED, NO_FORCE_OPERATION_PERFORMED.

Next required human steps are protected-environment setup and narrowly scoped
policy-adoption review. The existing Draft PR adds only code, tests and docs;
it makes no Workflow/policy/branch protection change.

Official guidance:
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments
- https://docs.github.com/en/actions/how-tos/managing-workflow-runs-and-deployments/managing-deployments/reviewing-deployments
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository
