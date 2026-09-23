# controller-throughput

Portable liveness and throughput rules for scheduled work controllers.

## Problem owned

A controller should spend its scheduled invocation doing useful work, not serializing every mechanical action behind the next hourly invocation.

The fundamental unit is:

```text
one controller invocation
  = one bounded work burst
  = continue synchronous safe work
    until an external wait boundary, hard hold, or bounded budget is reached
```

It is not `one invocation = one mutation`.

## Liveness classifications

```text
SYNC_AUTHORITY
  scheduled ACTIVE/PAUSED intent disagrees with durable canonical work state

MISSING_VALIDATION_ROUTE
  required exact-head validation was expected but zero exact-head runs exist

BURST_ADVANCE
  one ready task can progress now

PARALLEL_ADVANCE
  multiple independent ready tasks can progress under the configured lane budget

WAIT_EXTERNAL
  an active validation blocks all currently ready work

IDLE
  no task is currently declared ready

PAUSED
  explicit pause is the desired authority state
```

`MISSING_VALIDATION_ROUTE` is a FIX state, not a WAIT state. Re-checking the same zero-run condition on the next schedule without repairing the trigger is a liveness defect.

## Validation-route rule

After an operation that is supposed to launch exact-head validation, confirm that an exact-head run exists. This is launch confirmation, not busy polling.

```text
expected launch + exact_head_runs == 0
  -> MISSING_VALIDATION_ROUTE
  -> repair trigger / explicitly trigger validation
  -> do not spend later cycles waiting for a run that does not exist
```

Retargeting a PR to a monitored base is a common failure mode because workflow event filters may not run on a base edit unless the consumer explicitly covers that event.


When the missing route is a GitHub Actions execution problem, delegate route
selection to the trigger-loaded `github-actions-execution` skill. The
throughput skill should consume its result rather than deciding between
`workflow_dispatch`, existing triggers, reruns, or one-shot workflows itself.

`ROUTE_READY` means the validation route is repairable/executable through the
selected route. Only `NO_AUTHORIZED_ROUTE` or `NO_SAFE_EQUIVALENT_ROUTE`
constitutes a real execution-route gate.

## Work-burst rule

Within one invocation:

1. fresh-read mutable state that will actually affect the decision;
2. perform all causally ordered synchronous low-risk steps that remain interpretable and reversible;
3. when a new asynchronous validation/review is launched, confirm the route exists;
4. use remaining useful work time on dependency-independent read-only or safely unlocked work;
5. a natural later status read is allowed; do not sleep/busy-poll merely to wait for completion;
6. stop when all ready work is behind an external wait boundary.

This preserves evidence gates without turning a short CI job into an automatic one-hour delay.

## Scoped locks

Consumers should distinguish:

```text
GLOBAL
  pending evidence can be invalidated by any canonical mutation
  -> all mutation waits

SCOPED
  pending evidence owns explicit branch/resource/evidence keys
  -> conflicting mutation waits
  -> dependency-independent non-overlapping work may proceed

NONE
  no active validation mutation lock
```

A lock is about evidence validity, not repository-wide inactivity.

## Durable authority rule

Before enabling a scheduled controller to resume a previously paused campaign, scheduler desired state and durable canonical work state must agree. If the canonical checkpoint still says PAUSED, first write a durable resume checkpoint. A prompt-only resume is insufficient.

## Differential context refresh

`fresh-read` means current truth for mutable targets relevant to the next decision. It does not mean re-reading every canonical protocol or every issue on every invocation.

Reload canonical rule owners when their pinned revision changed, the phase changes, a trigger requires a new pack, current evidence contradicts the durable checkpoint, or the controller cannot establish the next action from the compact checkpoint.

Otherwise use:

```text
durable controller checkpoint
+ active work item
+ current branch/head
+ relevant CI/review state
+ changed dependency surfaces
```

## CLI

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli controller throughput --input controller-throughput.json
PYTHONPATH=src python3 -m chatgpt_operation.cli controller throughput-self-test
```

The central skill is repository-agnostic. The consumer owns task readiness, dependency edges, resource keys, validation meaning, and scientific acceptance.
