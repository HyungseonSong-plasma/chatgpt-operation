# ChatGPT Operation Operating System

**Status:** canonical operating-system registry  
**Canonical owner:** `HyungseonSong-plasma/chatgpt-operation`  
**Current version name:** Samuel  
**Current baseline date:** 2026-10-08  
**Current generation:** Controller-Native / Skill-Optimized  
**Predecessor:** Paul — historical

This directory owns named ChatGPT operating-system baselines, lifecycle, the minimal common rule layer, and cross-repository version-management policy.

## Current operating system

`Samuel` is ACTIVE.

Samuel preserves Paul's minimal-rule / skill-delegation model and promotes the durable controller, capability registry, trusted validation, exact-head native GitHub mutation, and deterministic recovery paths into the canonical operating architecture.

Samuel's live composition is:

```text
exact central revision
  -> Samuel essential rules
  -> trigger-resolved deterministic skills
  -> durable controller state and capability routing
  -> consumer-local semantic/scientific authority
  -> current evidence and first real gate
```

Canonical Samuel entry points:

```text
docs/operating_system/ESSENTIAL_RULES.md
docs/operating_system/EVOLUTION.md
docs/operating_system/versions/2026-10-08_samuel.md
skills/session-bootstrap/README.md
skills/catalog.json
skills/capability-registry.json
.github/workflows/samuel-controller.yml
.github/workflows/samuel-native-github.yml
```

## Samuel operating model

Samuel keeps the same irreducible common-rule philosophy introduced by Paul, but moves execution authority into tested deterministic controller paths.

The active architecture is:

```text
MINIMAL ESSENTIAL RULES
  authority / semantic / evidence / gate invariants
        |
        v
TRIGGER-RESOLVED SKILLS + CAPABILITY REGISTRY
  bootstrap / state refresh / mutation / governed work / PR merge / observation
        |
        v
DURABLE SAMUEL CONTROLLER
  state checkpointing
  exact-head trusted validation
  native GitHub read-before/write/read-after execution
  deterministic recovery
        |
        v
CONSUMER LOCAL AUTHORITY
  domain/scientific semantics
  acceptance criteria
  repository-specific policy
```

The canonical minimal rule layer is `ESSENTIAL_RULES.md`.

## Ownership boundary

```text
chatgpt-operation
  -> OS identity/version lifecycle
  -> Samuel essential common rules
  -> reusable deterministic operating skills
  -> capability routing
  -> durable generic controller mechanics
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

A central skill or controller result cannot redefine consumer-domain truth.

## Consumer binding contract

A consumer binds to one **exact immutable commit SHA** of this repository for an operating decision cycle.

Recommended metadata:

```json
{
  "operating_system": {
    "repository": "HyungseonSong-plasma/chatgpt-operation",
    "revision": "<exact-commit-sha>",
    "index": "docs/operating_system/README.md",
    "expected_version": "Samuel"
  }
}
```

Rules:

1. do not follow `main`, `latest`, or another floating ref after binding;
2. initialize by verifying Samuel and `ESSENTIAL_RULES.md` at the exact revision;
3. load only required init skills, then trigger-load later skills/capabilities;
4. a central update does not silently upgrade a pinned consumer;
5. consumer adoption of a new central revision is an explicit repository change;
6. consumer-local domain/scientific authority remains local;
7. execution requires the owning skill/controller contract and fresh decision-critical evidence.

## Samuel initialization

The portable generic sequence remains owned by `skills/session-bootstrap`.

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

The lightweight central trigger registry is `skills/catalog.json`. During initialization, `session-bootstrap` indexes this metadata and may trigger-load the skill required by the immediate obligation after current consumer state is known. Capability-backed work is resolved through `skills/capability-registry.json`; this does not grant mutation authority during initialization.

## Live skill/controller set

Samuel's central reusable mechanics currently include:

```text
session-bootstrap
state-refresh
repository-mutation
governed-work
controller-throughput
controller-lifecycle
github-actions-execution
github-actions-observation
pull-request-merge
research-controller
```

The existence of a skill does not imply permanent activation. Skills are loaded only when their trigger applies.

Key Samuel controller surfaces include:

```text
samuel-controller.yml
samuel-native-github.yml
samuel-trusted-pr-validation.yml
samuel-diagnostic-recovery.yml
samuel-repository-mutation.yml
```

## Operating metrics

Calvin-era rule-application metrics remain retired from live operation. Samuel, like Paul, is evaluated through contract correctness, adversarial qualification, fail-closed behavior, exact-revision adoption, deterministic recovery, consumer parity, and real repository behavior.

This retirement does **not** apply to scientific, numerical, runtime, performance, or validation metrics owned by a consumer's technical domain.

## Historical baselines

Named historical baselines remain immutable:

```text
docs/operating_system/versions/2026-09-01_calvin.md
docs/operating_system/versions/2026-09-20_paul.md
```

Do not rewrite those files to Samuel terminology.

## Version log

| Baseline date | Version | Generation | Record | State |
|---|---|---|---|---|
| 2026-09-01 | Calvin | Rule-Optimized | `versions/2026-09-01_calvin.md` | HISTORICAL |
| 2026-09-20 | Paul | Rule-Minimal / Skill-Optimized | `versions/2026-09-20_paul.md` | HISTORICAL |
| 2026-10-08 | Samuel | Controller-Native / Skill-Optimized | `versions/2026-10-08_samuel.md` | ACTIVE |

## Versioning discipline

For future OS changes:

1. preserve prior named baselines unchanged;
2. distinguish essential rules from deterministic skill/controller mechanics and consumer-local semantics;
3. prefer contract tests, adversarial cases, fail-closed behavior, consumer parity, exact-head mutation, and durable recovery over rule-count or rule-application scores;
4. preserve domain/scientific authority boundaries;
5. create a new immutable baseline only for a material OS-generation change;
6. require each consumer to adopt the new exact central revision explicitly.

A version name identifies an operating architecture, not a score.
