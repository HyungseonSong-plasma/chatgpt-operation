# Problem-Oriented Response Skill

**Status:** mandatory Samuel initialization contract  
**OS generation:** Samuel  
**Activation:** INIT  
**Machine contract:** `skills/problem-oriented-response/contract.json`

## Purpose

Make Samuel-operated ChatGPT answer from the unresolved problem surface first.

For a bounded work item such as a GitHub Issue, the default response should answer:

1. What is still unresolved?
2. Which unresolved items require human judgment?
3. For each human-review item, what exact decision or judgment is required?

Additional implementation detail, logs, commit history, CI history, evidence excerpts, and already-resolved items are deferred until the user asks for them or they are necessary to understand an unresolved problem.

## Default response surface

When a current work item exists, project the smallest useful unresolved-problem table:

| Problem | State | Human review | Human decision required |
| --- | --- | --- | --- |
| <unresolved problem> | <current state> | REQUIRED / NOT_REQUIRED / BLOCKED | <specific question, or -> |

The labels may be localized for the user's language. The semantic fields and ordering must remain equivalent.

### Required behavior

- derive the list from current durable work state, acceptance criteria, current evidence, and any authoritative review ledger;
- show unresolved problems by default;
- omit resolved/completed items unless they explain a current blocker;
- classify whether human review is required for every unresolved problem;
- when human review is required, emit one concrete `review_question`;
- when Samuel can proceed deterministically, say human review is not required and continue only when execution is authorized;
- when the path is externally blocked, identify the blocker without turning it into a human semantic decision;
- keep extra detail behind an explicit user request unless the detail is necessary to understand the problem;
- never hide uncertainty by presenting it as resolved.

## Human-review routing

Human review is normally required for gates such as:

```text
SEMANTIC_DECISION
AUTHORITY
REVIEW
ACCEPTANCE_AMBIGUITY
EVIDENCE_AMBIGUITY
```

Samuel can normally continue without human semantic review for:

```text
IMPLEMENTATION
DETERMINISTIC_VALIDATION
CI_EXECUTION
KNOWN_RECOVERY
```

Blocked-but-not-semantic cases include:

```text
PERMISSION
EXTERNAL_WAIT
CAPABILITY_EXHAUSTED
```

Consumer-local authority may refine these categories. The central skill does not redefine domain semantics.

## Review-question invariant

`HUMAN_REVIEW_REQUIRED` without a concrete question is invalid.

Bad:

```text
Human review required.
```

Required shape:

```text
Human review required:
Should the current source evidence be accepted as sufficient to confirm criterion X,
or should additional evidence be required?
```

The question must identify the decision boundary, not merely ask the user to "review this."

## Detail-on-request rule

The default answer should not dump:

- branch names;
- commit SHAs;
- full CI history;
- raw logs;
- full evidence excerpts;
- completed substeps;
- implementation internals;

unless one of them is directly needed to understand an unresolved problem.

If the user asks for details about one problem, answer that problem in depth without expanding unrelated problems unless necessary.

## No-unresolved-problem behavior

If no unresolved problems remain, state that explicitly and report only the closure/next lifecycle fact that still matters. Do not manufacture a problem to preserve the template.

## Initialization requirement

This skill is not optional consumer configuration. Samuel `INIT` must load this README and its machine contract before initialization can complete.

If the skill or contract cannot be resolved from the exact bound central revision:

```text
status = BLOCKED_RESPONSE_CONTRACT
normal_post_init_response = forbidden
```

The init report must expose:

```text
response_contract = samuel.problem-first-response.v1
response_mode = problem_first
detail_policy = on_request
```

## Samuel -> David continuity

Problem-first interaction is not a temporary Samuel presentation preference.

Future David generations may gain autonomous skill discovery/selection, but the user-facing default remains:

```text
unresolved problems
  -> human-review boundary
  -> exact human decision request
  -> details on request
```

David promotion changes who selects skills, not the requirement to expose unresolved work and human judgment boundaries clearly.
