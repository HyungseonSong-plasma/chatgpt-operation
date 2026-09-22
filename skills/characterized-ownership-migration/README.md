# characterized-ownership-migration

**Status:** portable skill contract  
**OS generation:** Paul  
**Activation:** trigger-loaded when an accepted refactor moves responsibility from one canonical owner to another.

## Purpose

Provide a deterministic migration discipline for ownership cutovers without embedding consumer-domain semantics.

The skill answers:

```text
what must be proven before an old owner can be retired?
what evidence permits caller cutover?
when is dual authority still present?
what validation must remain separate from domain/scientific acceptance?
```

It does not decide whether a proposed architecture is desirable.

## Owns

This skill owns the generic sequence:

```text
accepted migration intent
  -> owner / caller census
  -> behavior-contract characterization
  -> target-owner readiness
  -> migration batch
  -> parity validation
  -> canonical caller cutover
  -> zero-canonical-caller proof
  -> old-owner retirement
  -> exact-head validation
  -> durable migration evidence
```

It also owns the generic fail-closed gates that prevent premature retirement or parallel semantic authority.

## Does not own

The skill does not decide:

- scientific or domain semantics;
- solver/backend-specific realization choices;
- protocol meaning;
- compatibility commitments;
- which implementation should become canonical;
- repository-specific review/merge authorization;
- numerical or physical acceptance;
- whether protocol/runtime success upgrades a scientific result.

Those remain consumer-owned.

## Required consumer inputs

A migration request should identify:

```text
migration_id
source_owner
target_owner
accepted_intent_reference
canonical_caller_scope
characterization_evidence
target_readiness_evidence
parity_evidence
retirement_targets
validation_requirements
domain_acceptance_boundary
```

The caller scope must distinguish canonical production callers from historical fixtures, archived provenance, or explicitly retained compatibility paths.

## Migration states

```text
PLANNED
CHARACTERIZED
TARGET_READY
MIGRATING
PARITY_ESTABLISHED
CUTOVER_READY
CUTOVER_COMPLETE
RETIREMENT_READY
RETIRED
VALIDATED
BLOCKED
```

A consumer may use a richer local state machine, but may not skip the invariants below.

## Algorithm

### OM-01 — Confirm accepted intent

Require durable evidence that the ownership move itself is already accepted.

If architecture or semantic ownership is still undecided:

```text
status = BLOCKED_DECISION
```

This skill does not resolve that decision.

### OM-02 — Census owners and callers

Enumerate:

- current source owner(s);
- proposed target owner;
- canonical production callers;
- compatibility callers;
- historical/provenance-only references;
- tests and CI contracts coupled to the source owner.

An incomplete caller census blocks retirement.

### OM-03 — Characterize the source contract

Before moving behavior, identify the externally relevant contract:

```text
inputs
outputs
sign/unit conventions
error/failure semantics
side effects
ordering/lifecycle semantics
compatibility envelope
evidence/observability obligations
```

Characterization may be tests, fixtures, recorded evidence, or other deterministic contracts.

Moving uncharacterized behavior is not an accepted migration.

### OM-04 — Establish target readiness

Require evidence that the target owner can represent the characterized contract without redefining consumer-owned semantics.

If target capability is missing, return:

```text
status = BLOCKED_TARGET_CAPABILITY
```

Do not create parallel semantic authority as a workaround.

### OM-05 — Execute a bounded migration batch

Prefer the smallest ownership batch that can be independently validated.

A batch must identify:

- exact source surface;
- exact target surface;
- callers included in the batch;
- callers intentionally deferred;
- expected post-state.

Unrelated cleanup should remain outside the batch.

### OM-06 — Prove parity before canonical cutover

Validate the dimensions material to the characterized contract, for example:

```text
construction parity
failure parity
runtime behavior parity
evidence/observability parity
compatibility parity
```

Domain/scientific parity remains consumer-defined.

Protocol success or successful execution alone is insufficient.

### OM-07 — Cut over canonical callers

Only after required parity is established:

```text
canonical callers -> target owner
```

During a bounded cutover window, compatibility references may remain if they are explicitly classified and cannot act as competing canonical owners.

### OM-08 — Prove zero canonical callers to the source owner

Retirement requires a complete source-reference scan showing:

```text
canonical_source_callers = 0
```

Historical fixtures and archived provenance may remain only when explicitly classified as non-canonical.

### OM-09 — Retire the old owner

Delete, archive, or otherwise demote the source owner only after OM-08.

Retirement must not silently remove required compatibility or provenance evidence.

### OM-10 — Validate exact post-state

Run the consumer-declared exact-head validation set.

The migration is not complete until the post-state is verified at the exact revision that contains the retirement/cutover.

## Core invariants

```text
CHARACTERIZATION_BEFORE_MOVE = true
PARITY_BEFORE_CANONICAL_CUTOVER = true
RETIRE_BEFORE_PARITY = false
RETIRE_WITH_CANONICAL_CALLERS = false
DUAL_CANONICAL_SEMANTIC_AUTHORITY = false
EXACT_HEAD_VALIDATION = required
PROTOCOL_PASS_IMPLIES_DOMAIN_PASS = false
RUNTIME_PASS_IMPLIES_SCIENTIFIC_PASS = false
```

## Failure classifications

- `BLOCKED_DECISION` — ownership direction or semantics unresolved.
- `BLOCKED_CENSUS` — owner/caller/reference census incomplete.
- `BLOCKED_CHARACTERIZATION` — source contract not sufficiently characterized.
- `BLOCKED_TARGET_CAPABILITY` — target cannot represent required contract.
- `PARITY_NOT_ESTABLISHED` — required parity evidence missing or failed.
- `CUTOVER_INCOMPLETE` — canonical callers still split.
- `RETIREMENT_BLOCKED` — source still has canonical callers or required compatibility ownership.
- `VALIDATION_FAILED` — exact post-state validation failed.
- `MIGRATION_VALIDATED` — all declared gates passed.

## Composition

Typical use:

```text
state-refresh
  -> current owner/caller evidence

characterized-ownership-migration
  -> migration state and next gate

repository-mutation
  -> bounded file/branch mutations

governed-work / governed-matrix
  -> deterministic validation execution

github-actions-observation
  -> exact CI/run correlation
```

Backend-specific skills may refine OM-03 through OM-06 but must not weaken the generic retirement invariants.

## Retry and interruption

Operational interruption is not migration failure.

After interruption:

1. refresh mutable owner/caller/CI evidence;
2. identify the last durably established gate;
3. resume from that gate;
4. never infer parity or retirement from chat memory alone.

A repeated migration step should converge toward the declared post-state and avoid duplicate semantic ownership.

## Evidence checklist

A validated migration record should be able to answer:

```text
What was the old canonical owner?
What is the new canonical owner?
Which behavior contract was preserved?
Which callers were cut over?
Which references remain and why are they non-canonical?
What parity evidence was required?
What exact revision was validated?
What domain/scientific claims were explicitly not established by the migration?
```
