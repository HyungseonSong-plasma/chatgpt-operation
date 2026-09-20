# Operating-System Evolution Model

**Status:** canonical generation model  
**Current generation:** Calvin — Rule-Optimized  
**Reserved successor:** Paul — Rule-Minimal / Skill-Optimized

This document defines the architectural distinction between named ChatGPT operating-system generations.

The generation boundary is determined by the **primary optimization surface**, not by whether a repository happens to contain rules or skills.

## 1. Calvin — Rule-Optimized generation

Calvin treats prompt-visible operating rules as the primary control surface.

Its optimization problem is:

```text
given a canonical rule inventory,
select the smallest relevant active rule working set
that preserves decision, prevention, and closure quality
```

The dominant mechanisms are:

```text
rule design
-> rule ownership
-> phase/rule routing
-> adaptive load/unload
-> weighted active-rule control
-> incident-driven rule/routing refinement
```

The primary efficiency question is:

> Which rules should be active for this context, and how can irrelevant rule context be avoided?

Skills may exist and be used during Calvin. Their existence does **not** make the system Paul. Under Calvin, deterministic skills are supporting mechanisms while the main operating architecture is still organized around selecting and managing prompt-visible rules.

Typical Calvin metrics therefore emphasize:

```text
active weighted rule load
working-set miss rate
false activation rate
missed activation rate
rule absent vs rule-not-loaded
trigger/routing miss rate
error rate versus active rule load
```

## 2. Paul — Rule-Minimal / Skill-Optimized generation

Paul changes the primary optimization problem.

Instead of mainly asking which rules should be loaded, Paul asks:

```text
what is the minimum irreducible rule layer,
and which reusable operating mechanics can be delegated
to deterministic, tested, versioned skills?
```

The target composition is:

```text
MINIMAL RULE LAYER
  irreducible invariants
  user authority / approval boundaries
  semantic ownership boundaries
  domain/scientific meaning
  skill trigger and delegation contracts
          |
          v
SKILL LAYER
  deterministic reusable mechanics
  state machines
  validation/lifecycle evaluators
  mutation mechanics
  structured evidence transforms
  repeatable bootstrap/controller mechanics
          |
          v
CONSUMER OVERLAY
  repository-specific policy
  domain semantics
  acceptance criteria
  current durable work state
```

The primary efficiency question becomes:

> Which prompt-visible rules are truly irreducible, and which deterministic procedures should be moved into reusable skills?

Paul therefore optimizes **rule minimization and skill delegation together**.

## 3. Rule-minimization rule

Rule minimization is not blind deletion, compression for its own sake, or replacing semantic judgment with code.

A rule is a candidate for skill delegation when its reusable part is substantially:

```text
deterministic
parameterizable
testable
versionable
portable across consumers
safe to fail closed
```

A rule should remain explicit when it owns or materially constrains:

```text
user authority
normative policy
domain semantics
scientific meaning
consumer-specific acceptance
irreducible judgment
skill activation conditions
skill output interpretation
```

The preferred Paul transformation is:

```text
verbose procedural rule
    ->
thin semantic/trigger contract
    +
tested deterministic skill
```

not:

```text
important semantic rule
    ->
hidden implementation assumption
```

## 4. Skill delegation gate

A local or central procedural rule may be minimized only after the proposed skill satisfies the applicable delegation gate:

```text
1. identify the deterministic mechanic being extracted
2. preserve the semantic/authority owner
3. define typed inputs, outputs, and failure states
4. cover negative/adversarial cases
5. require fail-closed behavior where uncertainty is material
6. demonstrate parity against the prior rule-governed procedure
7. pin an immutable skill revision
8. remove duplicated procedural prose only after adoption is verified
```

No rule is considered successfully minimized merely because equivalent code exists somewhere.

## 5. Paul working-set model

Paul still has a working set, but it is intentionally narrower.

```text
Calvin working set
  = CORE rules
  + phase rules
  + temporary rules
  + supporting skills as needed

Paul working set
  = minimal semantic/authority rules
  + current consumer-domain rules
  + skill trigger/delegation contracts
  + only the deterministic skills required by the current obligation
```

Paul therefore does **not** replace rule overload with skill overload. Skill activation should also remain demand-driven and bounded.

## 6. Calvin -> Paul architectural delta

| Dimension | Calvin | Paul |
|---|---|---|
| Primary optimization surface | active rule set | irreducible rule layer + skill delegation |
| Prompt-visible procedure | substantial | minimized |
| Deterministic mechanics | may remain in rules or skills | preferentially skill-owned |
| Rule-working-set optimization | primary | retained but secondary |
| Skill selection | supporting | first-class |
| Portability mechanism | reusable rules/protocols | deterministic skills + thin semantic contracts |
| Main context-cost control | load/unload rules | remove delegable procedure from rule context |
| Main failure question | was the right rule loaded? | should this be a rule, a skill, or a consumer semantic contract? |

## 7. Paul evaluation metrics

Where measurement coverage permits, Paul should add metrics that directly test the architectural transition:

```text
irreducible active rule load
procedural-rule reduction
skill delegation coverage
duplicate rule/skill ownership count
skill activation miss rate
false skill activation rate
skill parity failure rate
skill fail-closed correctness
deterministic-mechanic recurrence after delegation
prompt-context burden attributable to procedural rules
closure-quality regression rate
```

These complement rather than erase Calvin metrics. Historical rule-working-set metrics remain useful for comparison.

The target is not maximum skill count. A proliferation of narrow skills with overlapping ownership is also an operating-system failure.

## 8. Promotion meaning

Paul should become ACTIVE only when the system demonstrates that the new optimization axis is real:

```text
rule minimization is measurable
+
delegated mechanics are deterministic and tested
+
consumer semantics remain correctly owned
+
skill activation is reliable
+
closure/safety quality is preserved or improved
```

Adding several skills to a Calvin architecture is not sufficient.

Likewise, deleting rules without validated skill delegation is not Paul.

## 9. Historical preservation

The immutable Calvin baseline at:

```text
docs/operating_system/versions/2026-09-01_calvin.md
```

records Calvin as it existed at its baseline date and must not be rewritten to use later Paul terminology.

This document supplies the later cross-generation interpretation:

```text
Calvin = optimize the rule working set
Paul   = minimize the rule layer and optimize skill delegation
```
