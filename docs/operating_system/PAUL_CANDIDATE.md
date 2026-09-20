# Paul Successor Contract

**Status:** reserved successor; not active  
**Reserved version name:** Paul  
**Predecessor:** Calvin  
**Canonical owner:** `HyungseonSong-plasma/chatgpt-operation`  
**Purpose:** define the conditions and comparison contract for the next materially upgraded ChatGPT operating-system baseline without prematurely declaring that upgrade complete.

## 1. Successor rule

`Paul` is reserved for the first operating-system baseline that materially supersedes Calvin.

Until that promotion occurs:

```text
Current OS = Calvin
Reserved successor = Paul
Paul status = NOT ACTIVE
```

Do not use `Paul` for minor wording cleanup, documentation-only edits, routine skill additions, or ordinary consumer-local policy changes. Paul should represent a material operating change that can be evaluated against Calvin.

## 2. Material-upgrade criteria

At least one material cross-repository operating change should exist before promotion, for example:

```text
rule-selection / routing architecture materially changed
session-bootstrap architecture materially changed
activation or unloading policy materially changed
working-set sizing policy materially changed
controller lifecycle/throughput behavior materially changed
authorization or delivery-gate mechanics materially changed
incident-prevention loop materially changed
a new measurable control reduces a known Calvin failure mode
```

A model upgrade, consumer-domain change, or repository-specific workflow change by itself does not automatically create Paul.

## 3. Promotion gate

Before Paul becomes current, record:

```text
1. Calvin observation window and data coverage
2. the specific Calvin limitation or hypothesis being addressed
3. Paul architecture/policy delta
4. expected measurable effect
5. compatibility of pre/post metric definitions
6. known confounders: model version, repository changes, workload/complexity mix
7. representative consumer compatibility/parity evidence
8. activation date and central revision
```

Promotion must be explicit. Do not infer Paul activation merely because a central skill or consumer rule changed.

## 4. Calvin -> Paul comparison contract

Compare where measurement coverage permits:

```text
incident rate / bounded work item
known recurrence rate
pre-execution catch rate
gate-bypass rate
gate-defect rate
working-set miss rate
false activation rate
missed activation rate
bootstrap/routing failure rate
active weighted rule load by phase/role
error rate versus active weighted rule load
avoidable external-wait / serialization rate
closure-quality regressions
```

Consumers may add domain-specific metrics, but those metrics remain consumer-owned unless separately centralized.

The primary evaluation question is not whether Paul has more rules or more skills. It is whether Paul produces better operating decisions and prevention outcomes with equal or lower active-context/coordination burden and without weakening closure quality.

## 5. Hypothesis template

When Paul is proposed, create an explicit hypothesis such as:

```text
Compared with Calvin, Paul will reduce <target failure/routing/coordination metric>
while keeping <closure-quality guardrail> unchanged or improved,
under comparable workload and measurement coverage.
```

The hypothesis must be specific enough to be rejected by evidence.

## 6. Consumer evaluation

Before activation, evaluate at least the representative consumers named by the active migration/architecture decision.

For each consumer distinguish:

```text
central mechanic parity
consumer-local semantic parity
bootstrap/routing compatibility
mutation/validation safety
observed operating metrics
known unsupported surfaces
```

A central candidate may enter `SHADOW` while existing consumers remain pinned to Calvin.

## 7. Activation evidence

At Paul activation, create a dated immutable version baseline under:

```text
docs/operating_system/versions/YYYY-MM-DD_paul.md
```

That baseline should contain:

```text
activation date
central repository revision
Calvin comparison window
Paul architectural delta
initial working-set/bootstrap policy
changed activation patterns
retained Calvin invariants
retired or modified Calvin assumptions
representative consumer evidence
measurement plan
known confounders
```

Then update `docs/operating_system/README.md` so:

```text
Current version name = Paul
Calvin = historical baseline
```

Do not rewrite `versions/2026-09-01_calvin.md`.

Existing consumers pinned to a Calvin-era exact central revision remain on that revision until they explicitly adopt a Paul revision.

## 8. Decision states

Use these states while developing the successor:

```text
RESERVED
  Paul name is reserved; no successor implementation claim yet.

CANDIDATE
  A material successor design exists and is being evaluated.

SHADOW
  Paul logic is evaluated against Calvin without becoming current canonical OS authority.

ACTIVE
  Paul has passed the explicit promotion gate and is the current named central OS baseline.

REJECTED
  A proposed Paul design failed its hypothesis or created unacceptable regressions;
  Calvin remains current and the evidence is retained.
```

Current state:

```text
Paul = RESERVED
Calvin = ACTIVE
```

## 9. Preservation rule

Version evolution is itself experimental evidence. Preserve failed Paul candidates and rejected hypotheses when materially informative; do not retain only successful changes.

Central version history records operating-system evolution. Consumer repositories retain their own domain evidence and adoption history.
