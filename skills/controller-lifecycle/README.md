# controller-lifecycle

Portable lifecycle guard for scheduled ChatGPT work controllers.

## Problem owned

A scheduled controller must not disable itself because one repository search
returns an empty or incomplete result. This skill separates **business work
state** from **scheduler lifecycle state** and makes completion a two-phase,
deterministic decision.

## Terminal contract

A controller may disable itself for completion only when the evaluator returns:

```text
status = VERIFIED_COMPLETE
can_disable = true
```

The terminal predicate requires all of the following:

- primary open-work enumeration is complete and returns zero;
- a second, independently sourced open-work enumeration is complete and also returns zero;
- the configured controller/sentinel is explicitly terminal;
- active governed work/PR enumeration is complete and returns zero;
- a prior controller cycle already recorded the same terminal candidate token;
- the confirming cycle has a different observation ID.

The first valid terminal observation returns `TERMINAL_CANDIDATE` with
`can_disable=false`. Persist its candidate token durably, then re-check on a
later scheduled cycle. `scope_id` identifies the exact terminal-policy scope;
changing the work query/sentinel/active-work policy must change `scope_id`,
which invalidates any older terminal candidate.

## Failure semantics

```text
empty but incomplete enumeration -> WAIT, never COMPLETE
query/tool uncertainty            -> caller treats as no-disable
independent scans disagree        -> WAIT
open work remains                 -> ACTIVE
active work/PR remains            -> ACTIVE
sentinel still open               -> ACTIVE
first all-clear observation       -> TERMINAL_CANDIDATE
later matching all-clear          -> VERIFIED_COMPLETE
explicit user pause               -> PAUSED
```

A malformed evaluator input is an operational error. The caller must fail safe:
**do not disable the controller**.

## Snapshot shape

```json
{
  "schema_version": 1,
  "controller_id": "refactor-controller",
  "scope_id": "open-refactor-v1|controller-sentinel-v1|active-work-v1",
  "observation_id": "scheduled-run-2026-09-19T18:43:00+01:00",
  "explicit_pause": false,
  "primary_work_scan": {
    "complete": true,
    "open_count": 0,
    "method": "search-open-refactor",
    "evidence_id": "query-a"
  },
  "confirmation_work_scan": {
    "complete": true,
    "open_count": 0,
    "method": "controller-fanout-check",
    "evidence_id": "query-b"
  },
  "active_work_scan": {
    "complete": true,
    "open_count": 0,
    "method": "open-work-pr-check",
    "evidence_id": "query-c"
  },
  "sentinel": {
    "complete": true,
    "terminal": true,
    "method": "controller-issue-state",
    "evidence_id": "issue-state"
  },
  "previous_candidate": null
}
```

## Scheduled-controller integration rule

The scheduled controller owns evidence collection and candidate persistence.
The skill owns only deterministic lifecycle evaluation.

Recommended cycle:

```text
fresh repository evidence
  -> collect two independent work enumerations
  -> collect sentinel + active-work evidence
  -> controller evaluate
       ACTIVE/WAIT            -> remain enabled
       TERMINAL_CANDIDATE     -> persist candidate; remain enabled
       VERIFIED_COMPLETE      -> disable for completion
       PAUSED                 -> disable only because pause was explicit
```

Persist `candidate.token` and `candidate.observation_id` in a durable
controller checkpoint (for example the controller issue), not only in chat
context.

## CLI

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli controller evaluate \
  --input controller-snapshot.json

PYTHONPATH=src python3 -m chatgpt_operation.cli controller self-test
```

The central skill is repository-agnostic. Consumer-specific labels, issue
numbers, PR queries, scientific gates, and pause authority remain in the
consumer repository/controller.
