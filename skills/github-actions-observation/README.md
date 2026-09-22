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


## ChatGPT connector dispatch action contract

Issue #31 separates the authenticated connector action from the deterministic
runtime. A ChatGPT-hosted GitHub connector action should accept credential-free
arguments equivalent to:

```text
repository
workflow
ref
inputs
correlation_id
correlation_input
expected_head_sha
return_run_details = true
```

The connector/tool host owns the GitHub App credential and authenticated REST
transport. The raw credential must never be returned to the model, written into
the repository, or embedded in the dispatch receipt.

The portable helper
`chatgpt_operation.github.connector_dispatch.build_dispatch_action_request`
constructs this credential-free request. The connector action must resolve the
workflow registered on the default branch, dispatch it against the requested
branch/tag ref, and return:

```text
workflow_id
workflow_name/path
dispatch_status = 200 | 204
requested_at
workflow_run_id / run_url / html_url when GitHub supplies direct details
```

`normalize_dispatch_action_result` converts that response into the same receipt
consumed by the #26 observation runtime. A direct `workflow_run_id` is the
strongest causal binding. When direct details are absent, observation retains
the existing complete-enumeration/fail-closed rules; repeated same-ref/SHA
dispatches must not be silently conflated.

A connector action is an external host capability. Repository code can define,
test, and consume this contract, but cannot make an unavailable ChatGPT
connector action appear or access the connector-held GitHub credential.

The first validation target is `moose-test-repo#309`, using the
default-branch-registered `refactor.yml` dispatched against
`issue-309-standard-moose-sheath-refactor`. The Issue 309 manifest currently
exists on that feature branch rather than `main`, so dispatching `ref: main`
would select a control-plane revision that cannot resolve the manifest. The
request therefore pairs the feature-branch ref with its exact expected head SHA.
The workflow does not declare a correlation input, so the dispatch preserves its
supplied inputs exactly and relies on direct run details when available.


## Consumer mapping

Consumers may map observation statuses into their own state machines. For example, a controller may map `MATCHED_ACTIVE` to an external wait; a science workflow may report execution progress. Such mappings are consumer semantics and are not owned here.

## Trigger examples

- run this experiment and check the result;
- did the workflow_dispatch run start?;
- find the exact Actions run for this experiment;
- check CI for this SHA;
- why did this job fail?;
- scheduled controller validation checks.
