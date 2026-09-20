# Operating-System Evolution Model

**Status:** canonical generation model  
**Current generation:** Paul — Rule-Minimal / Skill-Optimized  
**Historical predecessor:** Calvin — Rule-Optimized

The generation boundary is determined by the primary optimization surface.

## Calvin — Rule-Optimized generation

Calvin treated prompt-visible operating rules as the primary control surface.

Its optimization problem was:

```text
given a canonical rule inventory,
select the smallest relevant active rule working set
that preserves decision, prevention, and closure quality
```

Its main mechanisms were rule design, rule ownership, phase/rule routing, adaptive load/unload, active rule-load control, and incident-driven rule/routing refinement.

Skills could exist under Calvin, but the operating architecture was still primarily organized around managing prompt-visible rules.

Calvin is preserved as historical baseline evidence at:

```text
docs/operating_system/versions/2026-09-01_calvin.md
```

## Paul — Rule-Minimal / Skill-Optimized generation

Paul changes the primary question to:

```text
what is the minimum irreducible rule layer,
and which reusable deterministic mechanics should be delegated
to tested, versioned skills?
```

Target composition:

```text
MINIMAL COMMON RULE LAYER
  authority boundaries
  semantic ownership boundaries
  claim/evidence boundaries
  real-gate invariants
        |
        v
DETERMINISTIC SKILL LAYER
  bootstrap
  state refresh
  mutation mechanics
  governed execution
  controller lifecycle/throughput
        |
        v
CONSUMER LOCAL LAYER
  domain/scientific semantics
  compatibility commitments
  repository policy
  acceptance criteria
  current durable state
```

The canonical common rule layer is `ESSENTIAL_RULES.md`.

## Rule minimization

A repeated operating behavior belongs in a skill when it is substantially:

```text
deterministic
parameterizable
testable
versionable
portable
safe to fail closed
```

A rule remains explicit when it materially owns:

```text
user authority
normative policy
domain semantics
scientific meaning
consumer-specific acceptance
irreducible judgment
skill activation/output interpretation
```

Preferred transformation:

```text
verbose repeated procedural rule
  ->
thin essential/semantic contract
  +
tested deterministic skill
```

## Common extraction

The Paul activation extraction across `simulation-ontology`, `sol-adapter-moose`, and `moose-test-repo` is recorded in:

```text
docs/operating_system/COMMON_RULE_EXTRACTION.md
```

That document classifies repeated material as:

```text
essential common rule
deterministic skill mechanic
consumer-local semantic rule
```

## Operating metrics retirement

Calvin used operating metrics because rule selection/application was itself the optimization target.

Paul does not use numeric rule-application or interaction-efficiency metrics as a live control surface.

Retired live OS metrics include:

```text
active weighted rule load
working-set miss/activation scores
GREEN/YELLOW/RED rule thresholds
WCC / T-WCC / RVR / EVR / DBR / RWR / CLR / FBR
incident-rate percentages used as rule-quality scores
```

Historical records are preserved for provenance only.

Paul is evaluated through:

```text
contract correctness
negative/adversarial tests
fail-closed behavior
consumer parity
exact-revision adoption
absence of duplicated deterministic procedure
preservation of semantic/scientific ownership
real repository behavior
```

No aggregate rule-application score is required.

Scientific/runtime/performance metrics used by consumer technical validation are not part of this retirement.

## Calvin -> Paul delta

| Dimension | Calvin | Paul |
|---|---|---|
| Primary optimization surface | active rule set | essential rules + skill delegation |
| Prompt-visible procedure | substantial | minimized |
| Deterministic mechanics | may remain in rules | skill-owned where portable |
| Rule-working-set tuning | primary | historical/secondary |
| Skill activation | supporting | first-class and trigger-based |
| Common authority rules | distributed/repeated | centralized minimal layer |
| Operating metrics | active optimization input | archival only |
| Consumer semantics | local | local |

## Future evolution

A future OS generation should not be justified by a better rule score.

A material successor should change the operating architecture itself and preserve:

```text
explicit authority
deterministic mechanics
fail-closed uncertainty handling
consumer semantic ownership
traceable exact-revision adoption
```

Historical named baselines remain immutable records of the architecture that actually existed.
