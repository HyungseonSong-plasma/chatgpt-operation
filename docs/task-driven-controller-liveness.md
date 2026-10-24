# Samuel: task-driven closed loop with hourly *stalled-task* recovery

**Scope:** Liveness scheduling only. This does NOT bypass repository mutation
policies, authenticate cross-repository work or grant merge permissions.

## Desired behaviour

```text
Explicit Samuel Issue opt-in (samuel label)
               |
               v
      Samuel Bootstrap (event)
               |
        real ActionPlan / work
               |
      bounded worker → terminal receipt → immediate bootstrap continuation
               |                              |
               +------------------------------+
               |
       complete / no runnable task
               v
             IDLE

 GitHub hourly liveness probe (0 * * * *)
               |
               +-- no opted-in, unresolved task → NO DISPATCH
               +-- blocked/needs human input → NO DISPATCH
               +-- any Bootstrap queued/running → NO DISPATCH
               +-- last Bootstrap ended < 3600 s ago → NO DISPATCH
               +-- unfinished task with >= 3600 s inactivity → DISPATCH
```

Previously `samuel-bootstrap.yml` had an unconditional
`20 13 * * *` daily schedule. This is removed. Task admission through
explicit `samuel` Issue labels and existing Samuel worker/terminal-completion
wake mechanisms remain untouched.

A distinct `samuel-task-watchdog.yml` retains an **hourly timer only as
a liveness probe**; it does not select any work if the durable admission
ledger and independently fetched open opted-in Issue set have no runnable
items. Checking hourly means actual recovery is at the first scheduled
probe after the full one-hour inactivity threshold has elapsed, not at an
exact 60-minute timestamp. GitHub may delay scheduled workflows.

`src/chatgpt_operation/controller/task_watchdog.py` is a deterministic,
fail-closed decision engine. It differentiates `WAKE / BUSY / DEFER /
IDLE / PAUSED` from malformed or incomplete evidence. `blocked`,
`revision_required` and `complete` never trigger retries. Only
`admitted`, `reasoning_required`, `planned`, `active` are eligible.
Running/queued Bootstrap instances preempt recovery. Last Bootstrap
`updated_at` must be at least 3600 seconds old. A one-hour cooldown
prevents hot loops when provider reasoning, CI or permissions stall.

The workflow reads exactly:
- open Issue pages explicitly labeled `samuel` in its **own repository**;
- the existing central #44 `samuel-work-admission` comment ledger;
- latest Bootstrap runs and independently fetched active/queued/waiting runs.

Missing/truncated/malformed identity evidence does not authorize a wake.
A `WAKE` only launches the existing Samuel Bootstrap workflow. The
Bootstrap owns ActionPlan correctness, CI and execution results; the
watchdog itself never writes target files or opens/merges PRs.

## Critical boundary: external codeQA #92

The existing controller currently discovers its **own repository** Issues.
The new watchdog preserves that restriction. It does not silently treat
`HyungseonSong-plasma/codeQA#92` as a central Issue #92, claim completion
of a cross-repo task, or alter the protected
`automation/samuel/repository-mutation-policy.json`.

Extending this task-driven lifecycle to codeQA requires the *remaining*
governed cross-repository authorization, Issue identity routing, work
evidence/terminal completion, and target PR/CI operations described in
[Samuel Issue #220](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/220).
Until that path has **real E2E proof**, this is a tested liveness primitive,
not a working autonomous codeQA implementer.

## Safety tests

`tests/test_task_watchdog.py` verifies first-task lost wake recovery,
no wake without an opted-in task, one-hour cutoff, no duplicate in-flight
dispatch, suspended/bad Issue states, malformed/incomplete run enumeration,
correct latest-run selection and removal of the legacy daily Bootstrap
schedule. Controller's existing terminal-persistence continuation stays
intact.

Do not run multiple independent watchdog workflows against the same
controller state without coordination or a task-scoped lease; workflow
`concurrency: samuel-task-recovery` serializes this implementation's
liveness checks, while `samuel-bootstrap` serializes the worker root.
