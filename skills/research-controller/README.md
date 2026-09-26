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

## Mandatory executable consistency contracts

Before architecture/workflow reasoning, the controller must execute these code-owned contracts:

- `decision-registry` -> `chatgpt_operation.controller.decisions.DecisionRegistry`
- `implementation-state` -> `chatgpt_operation.controller.implementation.ImplementationState`
- `reasoning-envelope` -> `chatgpt_operation.controller.envelope.build_reasoning_envelope`
- `decision-guard` -> `chatgpt_operation.controller.decisions.DecisionGuard`

Required order:

```
load accepted decisions
-> load implementation state
-> build bounded ReasoningEnvelope
-> run typed reasoning
-> validate with DecisionGuard
-> produce typed decision / ActionPlan
```

Accepted architecture and implementation status are separate state. A missing implementation must be treated as an implementation gap, not rediscovered as a new architecture decision. An incompatible proposal must use an explicit versioned revision transaction; otherwise fail closed.

## Native GitHub execution boundary

Repository-governing GitHub mutations use `chatgpt_operation.github.native_executor`.

The v0 action vocabulary is closed-world:

- `MERGE_PR`
- `COMMENT_ISSUE`
- `CLOSE_ISSUE`
- `DISPATCH_WORKFLOW`

Execution order is code-owned:

```
read current state
-> return NOOP if desired postcondition already holds
-> validate exact preconditions / reject stale state
-> mutate through injected native runtime port
-> read back state
-> verify desired postcondition
-> return typed ExecutionResult
```

The LLM/connector is not the execution authority. A GitHub-native service or workflow supplies the read/mutate ports.
