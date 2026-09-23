# ChatGPT Operation Operating System

**Status:** canonical operating-system registry  
**Canonical owner:** `HyungseonSong-plasma/chatgpt-operation`  
**Current version name:** Paul  
**Current baseline date:** 2026-09-20  
**Current generation:** Rule-Minimal / Skill-Optimized  
**Predecessor:** Calvin — historical

This directory owns named ChatGPT operating-system baselines, lifecycle, the minimal common rule layer, and cross-repository version-management policy.

## Current operating system

`Paul` is ACTIVE.

Paul's live composition is:

```text
exact central revision
  -> Paul essential rules
  -> required deterministic skills
  -> consumer-local semantic/scientific authority
  -> current durable state and evidence
  -> first real gate
```

Canonical Paul entry points:

```text
docs/operating_system/ESSENTIAL_RULES.md
docs/operating_system/COMMON_RULE_EXTRACTION.md
docs/operating_system/EVOLUTION.md
docs/operating_system/versions/2026-09-20_paul.md
skills/session-bootstrap/README.md
skills/catalog.json
```

## Paul rule model

Paul does not optimize by continuously growing, scoring, or tuning a large prompt-visible rule system.

It keeps only irreducible common rules covering:

```text
durable authority
exact central pinning
read-only fail-closed initialization
central-vs-consumer semantic ownership
fresh mutable evidence before mutation/current-state claims
evidence-class boundaries
real unresolved gates
durable checkpoint/resume
documentation truth
```

Reusable deterministic procedure belongs in skills.

The canonical minimal rule layer is `ESSENTIAL_RULES.md`.

## Ownership boundary

```text
chatgpt-operation
  -> OS identity/version lifecycle
  -> Paul essential common rules
  -> reusable deterministic operating skills
  -> cross-repository binding rules

consumer repository
  -> domain semantics
  -> scientific meaning
  -> compatibility commitments
  -> repository-specific policy
  -> roles/modes where local
  -> local acceptance criteria
  -> durable current work state
  -> domain/runtime/scientific metrics and evidence
```

A central skill result cannot redefine consumer-domain truth.

## Consumer binding contract

A consumer binds to one **exact immutable commit SHA** of this repository for an operating decision cycle.

Recommended metadata:

```json
{
  "operating_system": {
    "repository": "HyungseonSong-plasma/chatgpt-operation",
    "revision": "<exact-commit-sha>",
    "index": "docs/operating_system/README.md",
    "expected_version": "Paul"
  }
}
```

Rules:

1. do not follow `main`, `latest`, or another floating ref after binding;
2. initialize by verifying Paul and `ESSENTIAL_RULES.md` at the exact revision;
3. load only required init skills, then trigger-load later skills;
4. a central update does not silently upgrade a pinned consumer;
5. consumer adoption of a new central revision is an explicit repository change;
6. consumer-local domain/scientific authority remains local.

## Paul initialization

The portable generic sequence is owned by `skills/session-bootstrap`.

A consumer supplies only:

```text
binding location
consumer authority entry points
durable work-state locator
current-evidence queries
required init skills
consumer-specific report additions
```

Initialization is read-only and fails closed when required operating authority cannot be verified.

The lightweight central trigger registry is `skills/catalog.json`. During
initialization, `session-bootstrap` indexes this metadata and may trigger-load
the skill required by the immediate obligation after current consumer state is
known. This does not preload every skill and does not grant execution authority.

## Live skill set

Paul's central reusable mechanics currently include:

```text
session-bootstrap
state-refresh
repository-mutation
governed-work
controller-throughput
controller-lifecycle
github-actions-execution
github-actions-observation
```

The existence of a skill does not imply permanent activation. Skills are loaded only when their trigger applies.

## Operating metrics retirement

The Calvin-era operating metrics used to assess rule loading/application and interaction efficiency are **retired from live Paul operation**.

Paul does not require:

```text
weighted rule-load scores
GREEN/YELLOW/RED rule-load thresholds
working-set effectiveness scores
WCC / T-WCC / RVR / EVR / DBR / RWR / CLR / FBR
rule-activation effectiveness percentages
mandatory metrics context during initialization
```

Historical values remain archival records of the Calvin period. They are not live authority, routing input, acceptance gates, or Paul evaluation requirements.

This retirement does **not** apply to scientific, numerical, runtime, performance, or validation metrics owned by a consumer's technical domain.

## Historical Calvin baseline

Calvin was the Rule-Optimized generation. Its immutable baseline remains:

```text
docs/operating_system/versions/2026-09-01_calvin.md
```

Do not rewrite that file to Paul terminology.

Calvin's historical optimization surface was the active rule working set. Paul supersedes it by minimizing common prompt-visible rules and delegating deterministic mechanics to skills.

## Version log

| Baseline date | Version | Generation | Record | State |
|---|---|---|---|---|
| 2026-09-01 | Calvin | Rule-Optimized | `versions/2026-09-01_calvin.md` | HISTORICAL |
| 2026-09-20 | Paul | Rule-Minimal / Skill-Optimized | `versions/2026-09-20_paul.md` | ACTIVE |

## Versioning discipline

For future OS changes:

1. preserve prior named baselines unchanged;
2. distinguish essential rules from deterministic skill mechanics and consumer-local semantics;
3. prefer contract tests, adversarial cases, fail-closed behavior, and consumer parity over rule-count or rule-application scores;
4. preserve domain/scientific authority boundaries;
5. create a new immutable baseline only for a material OS-generation change;
6. require each consumer to adopt the new exact central revision explicitly.

A version name identifies an operating architecture, not a score.
