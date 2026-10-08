# Operating-System Evolution Model

**Status:** canonical generation model  
**Current generation:** Samuel — Controller-Native / Skill-Optimized  
**Historical predecessors:** Paul — Rule-Minimal / Skill-Optimized; Calvin — Rule-Optimized

The generation boundary is determined by the primary control architecture.

## Calvin — Rule-Optimized generation

Calvin treated prompt-visible operating rules as the primary control surface.

Its optimization problem was:

```text
given a canonical rule inventory,
select the smallest relevant active rule working set
that preserves decision, prevention, and closure quality
```

Its main mechanisms were rule design, rule ownership, phase/rule routing, adaptive load/unload, active rule-load control, and incident-driven rule/routing refinement.

Calvin is preserved as historical baseline evidence at:

```text
docs/operating_system/versions/2026-09-01_calvin.md
```

## Paul — Rule-Minimal / Skill-Optimized generation

Paul changed the primary question to:

```text
what is the minimum irreducible rule layer,
and which reusable deterministic mechanics should be delegated
to tested, versioned skills?
```

Paul established:

```text
MINIMAL COMMON RULE LAYER
        |
        v
DETERMINISTIC SKILL LAYER
        |
        v
CONSUMER LOCAL SEMANTIC LAYER
```

That architecture materially reduced prompt-visible procedural duplication while preserving consumer-owned scientific/domain semantics.

Paul is preserved as historical baseline evidence at:

```text
docs/operating_system/versions/2026-09-20_paul.md
```

## Samuel — Controller-Native / Skill-Optimized generation

Samuel retains Paul's minimal rule layer and skill delegation, but changes the primary execution architecture from skill invocation alone to a **durable controller with explicit capability routing and verified mutation lifecycles**.

Samuel asks:

```text
which deterministic skill/capability owns this obligation,
what durable state proves where execution currently is,
and what exact preconditions/postconditions must be verified
before and after mutation?
```

Target composition:

```text
MINIMAL ESSENTIAL RULES
  authority / semantic / evidence / gate invariants
        |
        v
TRIGGER-RESOLVED SKILLS + CAPABILITY REGISTRY
  bootstrap
  state refresh
  repository mutation
  governed execution
  PR merge
  observation
        |
        v
DURABLE SAMUEL CONTROLLER
  action lifecycle
  durable state/checkpoint
  exact-head trusted validation
  native GitHub execution
  diagnostic/corrective recovery
  merge-conflict recovery
        |
        v
CONSUMER LOCAL LAYER
  domain/scientific semantics
  compatibility commitments
  repository policy
  acceptance criteria
  current domain evidence
```

The canonical common rule layer remains `ESSENTIAL_RULES.md`, now owned by Samuel.

## Samuel execution invariants

Samuel makes these mechanics first-class architecture rather than informal procedure:

```text
read authoritative state before mutation
persist dispatch intent before side effect
bind work to exact repository/branch/head identities
validate exact PR head before merge
require mergeable + CI success for native PR merge
read back desired postcondition after mutation
resume from durable lifecycle state after interruption
route rejected exact-head merges into deterministic recovery
resolve capabilities through a registered provider chain
```

The controller does not acquire scientific/domain authority by performing these mechanics.

## Rule minimization

A repeated operating behavior belongs in a skill/controller path when it is substantially:

```text
deterministic
parameterizable
testable
versionable
portable
safe to fail closed
recoverable from durable state
```

A rule remains explicit when it materially owns:

```text
user authority
normative policy
domain semantics
scientific meaning
consumer-specific acceptance
irreducible judgment
skill/capability activation and output interpretation
```

Preferred transformation:

```text
verbose repeated procedural rule
  ->
thin essential/semantic contract
  +
tested deterministic skill/controller lifecycle
```

## Operating metrics retirement

Calvin used operating metrics because rule selection/application was itself the optimization target.

Paul retired those metrics from live operation, and Samuel keeps them retired. Samuel is evaluated through:

```text
contract correctness
negative/adversarial tests
fail-closed behavior
exact-revision adoption
exact-head mutation safety
postcondition verification
durable recovery behavior
consumer parity
absence of duplicated deterministic procedure
preservation of semantic/scientific ownership
real repository behavior
```

Scientific/runtime/performance metrics used by consumer technical validation are not part of this retirement.

## Generation deltas

| Dimension | Calvin | Paul | Samuel |
|---|---|---|---|
| Primary control surface | active rule set | essential rules + skills | durable controller + skills/capabilities |
| Prompt-visible procedure | substantial | minimized | minimized |
| Deterministic mechanics | often rule-owned | skill-owned | skill/controller-owned |
| Durable execution lifecycle | secondary | partial | first-class |
| Capability routing | ad hoc | emerging | registered provider chain |
| Exact-head mutation verification | not architectural | skill-specific | canonical controller invariant |
| Recovery after interruption/rejection | procedural | bounded | durable deterministic path |
| Consumer semantics | local | local | local |
| Rule-application metrics | active | retired | retired |

## Future evolution

A future OS generation should change the operating architecture itself and preserve:

```text
explicit authority
deterministic mechanics
fail-closed uncertainty handling
durable checkpoint/resume
verified mutation identity and postconditions
consumer semantic ownership
traceable exact-revision adoption
```

Historical named baselines remain immutable records of the architecture that actually existed.
