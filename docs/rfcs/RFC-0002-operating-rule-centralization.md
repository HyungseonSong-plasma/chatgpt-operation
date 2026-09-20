# RFC-0002 — Portable Operating-Rule Centralization

**Status:** review only  
**Tracking issue:** #14  
**Consumers evaluated:** `sol-adapter-moose`, `moose-test-repo`

## Decision question

Which repeated repository-operating rules should become reusable deterministic skills in `chatgpt-operation`, which should be parameterized, and which must remain consumer-local domain policy?

## Design invariant

```text
chatgpt-operation
  -> generic deterministic operating mechanics

consumer repository
  -> domain semantics
  -> repository-specific policy
  -> scientific/compatibility meaning
  -> task readiness and acceptance criteria
```

Centralization is justified only when it reduces duplicated operating logic without moving domain truth into the central repository.

## Evidence baseline

```text
chatgpt-operation   ab9091e2eb2e1f186110a0afc5b1da4479349e1b
sol-adapter-moose  f35563f0e63e2739cb94a36c450d5d66024aff2a
moose-test-repo    a5e84e855c7aa85db145f587ed9d766c545a6023
```

Existing central skills:

- `state-refresh`
- `repository-mutation`
- `governed-work`
- `controller-lifecycle`
- `controller-throughput`

## Proposed candidates

### P0 — rule-working-set

Own generic mechanics for:

- minimum relevant active rule set;
- core / phase / temporary-pack composition;
- deterministic load/unload transitions;
- distinguishing rule absence from rule-not-loaded and routing/trigger defects;
- progressive disclosure instead of full rule-graph preload.

Consumer remains responsible for phase names, rule owners, domain triggers, and semantic meaning.

### P0 — session-bootstrap

Compose with `state-refresh` to restore the minimum safe operating context:

```text
resolve central revision
 -> load minimum operating mechanics
 -> restore repository identity
 -> restore durable work state
 -> restore active phase/rule set
 -> inspect current mutable evidence
 -> identify first real gate
 -> report uncertainty
```

Consumers define repository-specific bootstrap surfaces and report additions.

### P1 — work-authorization

Provide a deterministic generic authority state machine such as:

```text
DISCUSS_ONLY
PROPOSED
USER_APPROVED
ACCEPTED
EXECUTION_AUTHORIZED
PAUSED
BLOCKED
COMPLETE
```

The central mechanic must never allow prompt-only resume to override contradictory durable PAUSED/BLOCKED state. Consumers define which actions require which authority and where user approval is mandatory.

### P1 — delivery-gates

Evaluate evidence/lifecycle readiness without interpreting scientific meaning.

Candidate generic results:

```text
READY_TO_WORK
WAIT_VALIDATION
MISSING_VALIDATION_ROUTE
READY_TO_MERGE
MERGE_BLOCKED
READY_TO_CLOSE
MILESTONE_EXIT_REQUIRES_DECISION
```

Consumers supply exact-head policy, evidence requirements, review rules, merge rules, and milestone-exit policy.

### P2 — authority-resolution

Parameterized conflict-resolution evaluator:

- consumer supplies ordered authority classes;
- higher applicable authority wins;
- contradictions are surfaced instead of silently merged;
- lower-authority memory/docs cannot overwrite stronger current/canonical evidence.

### P2 — claim-evidence-boundary

Parameterized validator against invalid evidence promotion.

Consumer supplies:

```text
evidence classes
allowed implication edges
forbidden implication edges
required evidence per claim
```

Examples of generic invalid promotions:

```text
syntax acceptance      -X-> runtime success
runtime success        -X-> scientific validity
protocol conformance   -X-> numerical correctness
```

Concrete scientific and protocol taxonomies remain consumer-owned.

## Keep consumer-local

### sol-adapter-moose

Keep local:

- SOL Public Contract / Adapter Protocol semantics;
- SOL/MOOSE semantic authority boundary;
- MappingPlan / RealizationSpec meaning;
- MOOSE realization mappings;
- exact supported MOOSE package/application claims;
- thermal/plasma realization and V&V criteria;
- SOL Platform semantic escalation policy.

### moose-test-repo

Keep local:

- Physics-specific P0/P1/P2/P3 meaning;
- Physics runtime and environment evidence contracts;
- scientific model/regime acceptance;
- project-specific validation thresholds;
- Physics harness ownership and CLI conventions.

## Consumer fit

### sol-adapter-moose

Expected benefit:

- shrink always-loaded `AGENTS.md` obligations;
- make `moose-init` a consumer of one central bootstrap mechanism;
- centralize generic resume/merge/checkpoint mechanics;
- retain SOL/MOOSE semantic policy locally.

### moose-test-repo

Expected benefit:

- centralize mechanics already proven in `rule_working_set.md` and `BOOTSTRAP.md`;
- preserve its richer PLAN / RESEARCH / IMPLEMENT / VALIDATE / CLOSE phase model;
- avoid duplicating algorithms already externalized for state refresh and controller operation;
- retain Physics/scientific validity semantics locally.

## Review questions

1. Are any proposed skills actually domain policy disguised as mechanics?
2. Should any candidate extend an existing skill rather than create a new package?
3. Is `rule-working-set` deterministic enough to centralize?
4. Can `session-bootstrap` remain small instead of becoming a meta-framework?
5. Should authorization be standalone or integrated with lifecycle/bootstrap?
6. Where should delivery readiness stop and consumer acceptance begin?
7. Is parameterized authority resolution useful enough to encode?
8. Can claim/evidence promotion guards remain generic without flattening science?
9. Can both consumers adopt the same engine while retaining different role/phase models?
10. Does this reduce total operating complexity rather than relocate it?
11. What adversarial/self-tests are required before delegation?
12. Should a consumer pin one central revision for a whole decision cycle or pin skills independently?

## Proposed implementation sequence

```text
Batch 1
  rule-working-set
  session-bootstrap

Batch 2
  work-authorization
  delivery-gates

Batch 3
  authority-resolution
  claim-evidence-boundary
```

Each batch must be independently reversible and parity-tested against at least the two current consumers before local canonical rules are removed.

## Acceptance for this RFC

The design may leave review only when:

- central vs consumer ownership is explicit for every candidate;
- overlap with the five existing skills is resolved;
- both consumers have been evaluated;
- reuse/complexity benefit is demonstrated;
- adversarial cases are specified;
- the first implementation batch is bounded and reversible.

This RFC does not authorize consumer migration or deletion of local canonical rules.
