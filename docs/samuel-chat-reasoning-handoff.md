# Samuel chat-mediated reasoning handoff

## Operational decision

The owner selects **the currently open ChatGPT conversation** as the semantic
reasoning and typed ActionPlan drafting surface for interactive Samuel work.
Samuel's GitHub Actions remain deterministic policy, execution, verification,
evidence, and lifecycle workers. The production `samuel-bootstrap.yml` is
configured with `SAMUEL_REASONING_MODE=EXTERNAL` and **does not receive**
`OPENAI_API_KEY` or `SAMUEL_OPENAI_MODEL`.

This does **not** mean GitHub Actions can automatically invoke the interactive
ChatGPT conversation. A human-operated chat must observe the work and submit
its typed proposal through the connected, user-authorized GitHub account.
Unattended hourly watchdog runs may observe/continue deterministic in-flight
work but cannot generate a fresh semantic response on their own.

## Current handoff contract

1. Read the actual GitHub Issue, relevant immutable source revision,
   `skills/catalog.json`, capability registry, applicable skill contract,
   current ledger, previous denials and independent readbacks.
2. In ChatGPT, draft a typed `ReasoningSubmission` for an already-admitted
   `reasoning_required` work ID. The proposal is **not** an execution grant.
3. Post exactly one `<!-- samuel-reasoning-submission -->` JSON-fenced
   submission to central **Issue #44**, using the connected
   `HyungseonSong-plasma` account; never embed secrets. The user must
   authorize the specific work and the selected mutation.
4. The repository workflow wakes Bootstrap only for the matching owner
   comment on Issue #44. The deterministic consumer verifies the authoritative
   GitHub `comment.user.login` metadata (not text in the comment), exactly
   matches `work_id`, rejects duplicate trusted submissions, and passes the
   typed proposal through `DecisionGuard` and the existing ActionPlan checks.
5. Samuel's existing capability registry, mutation policy, exact-SHA guards,
   denial journal and postcondition verification remain authoritative.
   Protected changes continue through a reviewable PR/CI/merge gate.

### Limits

- The external submission format supports existing typed `ActionPlan` kinds.
  It **does not currently express `GITHUB_BRANCH_DELETE`** in the normal
  Production ActionPlan schema. Do not fabricate a DELETE payload or bypass
  the separately registered exact-SHA `branch_delete` skill contract.
- The preexisting Issue #255 reasoning failure is `escalated`. Switching to
  EXTERNAL does **not** clear it. The work identity, prior failure evidence,
  and authorized recovery path must be reconciled before another mutation.
- A past successful workflow is not evidence that a new GitHub write succeeded.
- Opt-in diagnostics or other separately governed workflows that previously
  used an OpenAI API key are **not** the ordinary Samuel Bootstrap reasoning
  path; their retirement requires a separately verified change.
- The trusted submitter setting belongs to the repository-owned workflow,
  not to the untrusted JSON proposal itself.
