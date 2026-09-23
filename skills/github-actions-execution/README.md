# GitHub Actions Execution Skill

**Status:** portable skill contract  
**OS generation:** Paul  
**Activation:** trigger-loaded only; normal Paul initialization does not load this skill.

## Purpose

Select a safe GitHub Actions execution route from current capabilities without
promoting one transport, especially `workflow_dispatch`, into an artificial
requirement.

The consumer/caller states the evidence claim that must be produced. This skill
deterministically selects an execution route and returns the required handoffs.

## Ownership boundary

This skill owns:

- execution-route sufficiency checks;
- event-preservation checks when the event itself is required evidence;
- exact-head preservation checks;
- boundedness and observability checks;
- one-shot eligibility;
- deterministic route precedence;
- mutation/observation/cleanup handoff obligations.

This skill does **not** own:

- scientific or domain acceptance;
- repository mutation authority;
- the semantic contents of a consumer workflow;
- whether a particular scientific claim is valid;
- GitHub connector credentials;
- GitHub Actions run correlation mechanics after launch.

Repository writes remain owned by `repository-mutation`. Run correlation and
terminal observation remain owned by `github-actions-observation`.

## Core invariant

```text
missing preferred mechanism
  !=
missing safe execution route
```

A missing `workflow_dispatch` action is not itself a blocker. It becomes a
blocker only when no authorized, bounded, observable route can preserve the
required claim.

If the event type itself is part of the required evidence, only a route with
that exact event is equivalent.

## Input contract

The planner consumes:

```text
request
  required_claim
  required_event          nullable
  require_exact_head
  mutation_authorized

routes[]
  id
  kind
  available
  authorized
  event
  preserves_exact_head
  observable
  bounded
  requires_repository_mutation
  cleanup_available
```

Supported route kinds:

```text
DIRECT_WORKFLOW_DISPATCH
EXISTING_WORKFLOW_TRIGGER
RERUN_EXISTING_RUN
ONE_SHOT_WORKFLOW
```

The caller supplies fresh capability evidence. The skill does not infer that a
tool or trigger exists merely because it existed in an earlier session.

## Eligibility

Every selected route must be:

- currently available;
- authorized;
- event-compatible when `required_event` is set;
- exact-head preserving when exact head is required;
- observable by the Actions observation path;
- bounded.

A route that requires repository mutation additionally requires
`mutation_authorized=true`.

A `ONE_SHOT_WORKFLOW` additionally requires:

- repository mutation;
- a cleanup route.

This makes a one-shot route a bounded fallback rather than an uncontrolled
permanent workflow mutation.

## Deterministic precedence

After filtering ineligible routes, select by fixed precedence:

```text
DIRECT_WORKFLOW_DISPATCH
  -> EXISTING_WORKFLOW_TRIGGER
  -> RERUN_EXISTING_RUN
  -> ONE_SHOT_WORKFLOW
```

Precedence selects among already sufficient routes. It never makes an
unavailable `workflow_dispatch` route block an eligible one-shot route.

## Results

`ROUTE_READY`

- one sufficient route was selected;
- `route_kind` and `route_id` identify it;
- `handoffs` describe the portable next mechanics.

`NO_AUTHORIZED_ROUTE`

- routes are available, but none is authorized.

`NO_SAFE_EQUIVALENT_ROUTE`

- no route satisfies event/head/observability/boundedness/mutation/cleanup
  constraints.

There is intentionally no `NO_WORKFLOW_DISPATCH` status.

## Handoffs

For a non-mutating route:

```text
github-actions-observation
```

For a one-shot route:

```text
repository-mutation
  -> github-actions-observation
  -> repository-mutation:cleanup
```

The one-shot workflow body is consumer-owned input. The central skill decides
whether that route is eligible; it does not invent consumer commands or
scientific semantics.

## Examples

Ordinary governed validation:

```text
required_event = null
direct workflow_dispatch unavailable
safe one-shot push workflow available

=> ROUTE_READY / ONE_SHOT_WORKFLOW
```

Event-specific integration test:

```text
required_event = workflow_dispatch
direct workflow_dispatch unavailable
safe push one-shot available

=> NO_SAFE_EQUIVALENT_ROUTE
```

## CLI

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli github plan-actions-execution \
  --input actions-execution.json
```

The schema is `schemas/github-actions-execution.schema.json`.
