# research-controller

Thin entrypoint for the code-first autonomous research controller.

Executable behavior is authoritative in Python, not in this document:

- `chatgpt_operation.controller.research` — persistent research state, stages, transitions, escalation routing.
- `chatgpt_operation.controller.reasoning` — typed Hypothesis/Analysis reasoning nodes with bounded repair.
- `chatgpt_operation.controller.action_plan` — typed, idempotent ActionPlan handoff.
- `chatgpt_operation.repository.action_plan_adapter` — repository-mutation adapter.
- `chatgpt_operation.github.action_plan_adapter` — GitHub Actions route adapter.
- `chatgpt_operation.controller.execution` — typed ExecutionResult feedback persisted into ResearchState.

## Invocation contract

1. Load the persisted `ResearchState`.
2. Run only the reasoning node required by the current stage.
3. Validate its typed result.
4. Let deterministic controller logic select the next stage.
5. Convert approved work into an `ActionPlan`.
6. Send the plan to the matching deterministic executor adapter.
7. Record the resulting `ExecutionResult` in `ResearchState`.
8. Resume from persisted state on the next controller cycle.

Do not encode research workflow rules here when they can be enforced in code.
Do not let free-form LLM output directly mutate repositories or bypass escalation.
