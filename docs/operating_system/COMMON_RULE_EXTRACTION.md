# Common Rule Extraction — Paul Activation

**Status:** activation analysis  
**Reviewed consumers:** `simulation-ontology`, `sol-adapter-moose`, `moose-test-repo`  
**Purpose:** separate repeated rules into essential common rules, deterministic skill mechanics, and consumer-local semantics.

## Result

The repeated operating content across the three consumers falls into three classes.

```text
A. irreducible cross-repository invariants
   -> Paul ESSENTIAL_RULES.md

B. deterministic reusable procedure
   -> central skills

C. domain / repository semantics
   -> remain consumer-local
```

## A. Essential common rules

The following repeated concepts are retained as Paul rules because they are authority/safety/claim boundaries rather than executable procedure:

| Common concept | Paul owner |
|---|---|
| durable repository authority beats chat memory | ER-01 |
| exact central revision; no floating substitution | ER-02 |
| init is read-only and fail-closed | ER-03 |
| central mechanics cannot override local semantics | ER-04 |
| current mutable evidence before write/current-state claim | ER-05 |
| evidence classes cannot be silently promoted | ER-06 |
| unresolved real gate stops affected path | ER-07 |
| resume from durable checkpoint/current evidence | ER-08 |
| documentation does not create semantic truth | ER-09 |

Consumers should reference these rules rather than reproduce their full generic wording.

## B. Deterministic procedure delegated to skills

The following recurring procedures are not Paul essential rules.

| Repeated procedure | Central owner |
|---|---|
| project/session initialization sequence | `skills/session-bootstrap` |
| delta refresh / immutable-pin reuse / prewrite refresh | `skills/state-refresh` |
| repository file/branch mutation mechanics | `skills/repository-mutation` |
| governed checked-in manifest execution | `skills/governed-work` |
| scheduled controller work-burst/liveness classification | `skills/controller-throughput` |
| scheduled controller completion/pause lifecycle | `skills/controller-lifecycle` |

Consumer documents supply configuration, semantic inputs, and triggers. They should not fork these algorithms into local prose.

## C. Rules that remain local

### simulation-ontology

Keep local:

- SOL ontology and Public Contract semantics;
- Adapter Protocol semantics;
- accepted ADR and compatibility/versioning authority;
- Manager/Planner/Researcher/Validator/Operator role meaning;
- roadmap/milestone/phase acceptance;
- SOL-specific cross-team decisions.

### sol-adapter-moose

Keep local:

- SOL/MOOSE authority boundary;
- supported Public Contract / Adapter Protocol compatibility;
- MappingPlan realization meaning;
- configured MOOSE application/backend facts;
- retry/replay side-effect semantics where defined by the adapter contract;
- MOOSE regression and physical/numerical V&V criteria;
- adapter-specific escalation and release gates.

### moose-test-repo

Keep local:

- Physics runtime evidence semantics;
- scientific model/regime validity;
- P0/P1/P2/P3 and validation meaning;
- production `physics-opt` evidence requirements;
- issue/milestone scientific acceptance;
- Physics/SOL consumer boundary and scientific execution contracts.

## Calvin rules retired as active Paul controls

Calvin optimized rule loading and measured rule/application behavior. Paul no longer uses the following as active OS control mechanisms:

- weighted active-rule-load thresholds;
- rule-load GREEN/YELLOW/RED sizing;
- working-set effectiveness metrics;
- WCC/T-WCC/RVR/EVR/DBR/RWR/CLR/FBR as OS/rule-quality metrics;
- incident recurrence percentages as a rule-application score;
- mandatory metrics bootstrap/context.

Historical records remain useful as provenance for why Paul was created, but they do not participate in Paul initialization, routing, acceptance, or promotion.

This retirement does **not** remove scientific, numerical, runtime, or performance metrics that are part of consumer-domain validation.

## Consumer migration principle

A Paul consumer should reduce its operating entry point toward:

```text
exact Paul binding
-> Paul essential rules
-> required init skills
-> consumer-local semantic authority
-> current repository evidence
-> first real gate
```

Mode-specific and action-specific skills are loaded only when triggered.

The target is lower prompt-rule burden without hiding semantic ownership.
