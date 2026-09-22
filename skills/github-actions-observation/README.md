# GitHub Actions Observation Skill

**Status:** portable skill contract
**OS generation:** Paul
**Activation:** trigger-loaded only; normal Paul initialization does not load this skill.

## Purpose

Establish deterministic GitHub Actions run evidence from a caller-supplied observation snapshot. The caller fetches current GitHub run/job/artifact evidence; this skill correlates that evidence to an expected execution request.

## Ownership boundary

This skill owns correlation mechanics and observation status only. It does not decide scientific validity, experiment acceptance, repository mutation authority, controller scheduling/liveness, or telemetry authority. GitHub Actions execution success is execution evidence only and does not imply scientific validity or experiment acceptance.

## Supported events

At minimum: `workflow_dispatch`, `pull_request`, `push`, and `schedule`.

## Correlation inputs

An observation request may constrain:

- workflow identity;
- event type;
- explicit correlation/request ID;
- expected head SHA;
- expected ref;
- dispatch/request time and visibility grace window;
- run attempt.

For `workflow_dispatch`, an explicit experiment/request identifier should be propagated into observable workflow/run evidence whenever the consumer can do so. SHA-only matching is insufficient for repeated dispatches.

## Result statuses

- `MATCHED_ACTIVE` — exactly one eligible run matches and is non-terminal.
- `MATCHED_TERMINAL` — exactly one eligible run matches and is terminal.
- `PENDING_VISIBILITY` — no eligible run is visible, but the request is still inside the configured eventual-consistency grace window.
- `NO_MATCH` — complete observation, grace expired, and no eligible or stale candidate exists.
- `AMBIGUOUS_MATCH` — more than one eligible run remains after all supplied constraints.
- `STALE_ONLY` — candidates satisfy identity constraints but fall outside the allowed request time/window.
- `OBSERVATION_INCOMPLETE` — enumeration is incomplete, required evidence is missing, or correlation cannot safely distinguish candidates.

## Required invariants

1. Incomplete enumeration fails closed as `OBSERVATION_INCOMPLETE`; it is never promoted to `NO_MATCH`.
2. Zero visible runs inside visibility grace is `PENDING_VISIBILITY`, not a missing validation route.
3. Wrong workflow, event, correlation ID, SHA, ref, or requested run attempt cannot be silently accepted.
4. Repeated dispatches on the same SHA/ref must not be conflated when a stronger correlation key is supplied or required.
5. Reruns are distinguished by `run_attempt` when that constraint is supplied.
6. A single exact eligible run determines active versus terminal from current run state/conclusion; domain acceptance remains consumer-owned.

## Snapshot model

The deterministic core accepts a JSON object with:

```text
request
  workflow_id/name
  event
  correlation_id (optional)
  head_sha (optional)
  ref (optional)
  requested_at
  visibility_grace_seconds
  run_attempt (optional)
observation
  observed_at
  enumeration_complete
  runs[]
```

Each run contains the observable fields needed for the supplied constraints, including workflow identity, event, run id, timestamps, head SHA/ref, run attempt, status/conclusion, and correlation ID when the caller has made one observable.


## Portable dispatch runtime

The deterministic evaluator remains usable with caller-supplied snapshots. For
GitHub-hosted execution, `chatgpt_operation.github.actions_runtime` adds a
repository-agnostic stdlib REST adapter:

```python
from chatgpt_operation.github.actions_runtime import (
    GitHubActionsTransport,
    dispatch_and_wait,
)

transport = GitHubActionsTransport(
    "OWNER/REPOSITORY",
    token,
)

result = dispatch_and_wait(
    transport,
    workflow="experiment-launcher.yml",
    ref="feature-branch",
    correlation_id="experiment-123",
    inputs={"mode": "smoke"},
    expected_head_sha="<expected-feature-branch-sha>",
)
```

The runtime performs:

```text
resolve workflow registered on default branch
  -> dispatch workflow against caller-selected branch/tag ref
  -> request direct workflow-run details when supported
  -> use returned workflow_run_id as causal binding
  -> observe active/terminal run
  -> fall back to complete workflow-run enumeration when direct details are absent
  -> feed normalized evidence into the deterministic evaluator
```

The target `ref` may be a non-default branch or tag. GitHub still requires the
dispatchable workflow definition itself to be registered on the repository
default branch.

For current GitHub Cloud, the runtime uses REST API version `2026-03-10` and
requests `return_run_details=true`. When GitHub returns the workflow run ID,
the receipt provides a direct causal binding between dispatch request and run.
Older/compatible surfaces that return an empty dispatch response fall back to
enumeration. If a supplied correlation ID cannot be observed strongly enough
during fallback, the evaluator fails closed instead of silently conflating
repeated dispatches.

CLI:

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli github dispatch-actions \
  --repository OWNER/REPOSITORY \
  --workflow experiment-launcher.yml \
  --ref feature-branch \
  --correlation-id experiment-123 \
  --input mode=smoke \
  --expected-head-sha <exact-sha> \
  --wait
```

Dispatch/observation success remains execution evidence only. Consumers retain
all scientific, acceptance, scheduling, and domain decisions.

## Consumer mapping

Consumers may map observation statuses into their own state machines. For example, a controller may map `MATCHED_ACTIVE` to an external wait; a science workflow may report execution progress. Such mappings are consumer semantics and are not owned here.

## Trigger examples

- run this experiment and check the result;
- did the workflow_dispatch run start?;
- find the exact Actions run for this experiment;
- check CI for this SHA;
- why did this job fail?;
- scheduled controller validation checks.
