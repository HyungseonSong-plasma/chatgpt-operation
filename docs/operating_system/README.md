# ChatGPT Operation Operating System

**Status:** canonical operating-system registry  
**Canonical owner:** `HyungseonSong-plasma/chatgpt-operation`  
**Current version name:** Calvin  
**Current baseline date:** 2026-09-01  
**Reserved successor:** Paul  
**Successor state:** RESERVED

This directory is the canonical owner of named ChatGPT operating-system baselines, their lifecycle, and cross-repository version-management policy.

The operating system is broader than any single skill or consumer repository. It defines how reusable operating mechanics, rule-selection architecture, bootstrap behavior, lifecycle controls, and empirical improvement are versioned as one coherent operating baseline.

## Ownership boundary

```text
chatgpt-operation
  -> OS version names and lifecycle
  -> immutable OS baseline records
  -> successor/promotion contracts
  -> reusable deterministic operating mechanics
  -> cross-repository consumer binding rules

consumer repository
  -> domain semantics
  -> repository-specific policy
  -> phase/role vocabulary where domain-specific
  -> scientific/compatibility meaning
  -> local acceptance criteria
  -> local metrics/evidence collection
  -> local bootstrap additions and durable work state
```

Central OS ownership does not make consumer-local domain truth generic.

## Current operating system

`Calvin` is the current named baseline.

Calvin was first established in `moose-test-repo` as the Adaptive Rule Working Set baseline. Its immutable historical record is preserved at:

```text
docs/operating_system/versions/2026-09-01_calvin.md
```

That record intentionally retains the repository/ref and MOOSE/QPX terminology that described the system at baseline time. Migration into this repository changes canonical storage ownership; it does not rewrite historical evidence.

Central ownership of the OS registry was established under tracking issue #16; the original historical baseline remains attributable to its source repository.

Calvin's defining objective is:

```text
minimum active rule load
subject to
acceptable decision, prevention, and closure quality
```

The current central reusable mechanics are implemented under `skills/`. A named OS baseline may span multiple skills and consumer-local overlays; the historical baseline record is not itself executable code and does not override current canonical skill contracts.

## Consumer binding contract

A consumer must bind operating-system authority to an **exact immutable commit SHA** of this repository for an operating decision cycle.

Recommended consumer metadata:

```json
{
  "operating_system": {
    "repository": "HyungseonSong-plasma/chatgpt-operation",
    "revision": "<exact-commit-sha>",
    "index": "docs/operating_system/README.md"
  }
}
```

Rules:

1. do not follow `main`, `latest`, or another floating ref as OS authority during an active decision cycle;
2. initialization resolves the exact central revision before loading central OS/skill contracts;
3. a central OS promotion does not silently upgrade an already-pinned consumer;
4. consumer adoption of a new OS revision is an explicit repository change with its own validation;
5. consumer-local canonical rules remain authoritative for domain semantics within the ownership boundary above.

A consumer may pin one central repository revision for the entire operating decision cycle rather than independently mixing skill revisions from different central commits.

## Live composition model

The intended composition is:

```text
central OS registry / exact revision
  -> central reusable operating mechanics
  -> consumer bootstrap
  -> consumer core invariants
  -> consumer routing / working-set metadata
  -> current durable work state
  -> current mutable evidence
```

The central registry supplies OS identity and reusable mechanics. The consumer supplies repository identity and domain-specific operating meaning.

## Reserved successor

`Paul` is reserved for the first materially upgraded operating-system baseline that supersedes Calvin.

Paul is **not active** merely because skills, protocols, or consumer documents continue to evolve. Minor cleanup, routine skill additions, or evidence updates remain Calvin unless an explicit successor promotion is made.

The successor contract is:

```text
docs/operating_system/PAUL_CANDIDATE.md
```

## Version log

| Baseline date | Version | Record | State |
|---|---|---|---|
| 2026-09-01 | Calvin | `versions/2026-09-01_calvin.md` | ACTIVE |
| future | Paul | `PAUL_CANDIDATE.md` until activation | RESERVED |

## Version lifecycle

```text
Calvin = ACTIVE current baseline
Paul   = RESERVED successor name
```

A successor may progress through:

```text
RESERVED -> CANDIDATE -> SHADOW -> ACTIVE
                         \
                          -> REJECTED
```

`SHADOW` is preferred when practical so a candidate can be compared against the current OS without silently changing consumer authority.

## Versioning discipline

When the operating system is materially upgraded:

1. preserve the preceding immutable baseline;
2. state the limitation or hypothesis motivating the successor;
3. record the architecture/policy delta and expected measurable effect;
4. compare observed metrics only where definitions, denominators, and coverage are compatible;
5. separate OS changes from model-version, repository, workload-mix, and domain-policy changes;
6. evaluate representative consumers before promotion;
7. create a new dated immutable version record only when the successor is explicitly activated;
8. update this registry;
9. let each consumer adopt the new exact revision explicitly.

A version name identifies an operating-system baseline. It does not claim that every consumer, rule, skill, or activation pattern has independently reached the same validation maturity.
