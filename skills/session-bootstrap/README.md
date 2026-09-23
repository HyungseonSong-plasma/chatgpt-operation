# Session Bootstrap Skill

**Status:** portable skill contract  
**OS generation:** Paul  
**Purpose:** restore a trustworthy minimum operating context for a new, resumed, or uncertain session without embedding consumer-domain semantics in the central layer.

## Owns

This skill owns the generic initialization sequence:

```text
consumer binding
-> exact central revision
-> Paul OS identity
-> Paul essential rules
-> required init skills
-> central skill catalog metadata
-> consumer repository identity
-> durable current work state
-> current decision-critical evidence
-> first real gate
-> immediate-obligation trigger resolution
-> triggered skill contracts for that obligation
-> concise initialization report
```

## Does not own

The skill does not decide:

- consumer domain semantics;
- scientific validity;
- compatibility commitments;
- consumer role names;
- issue/milestone acceptance;
- which domain documents are normative;
- mutation authority after initialization.

Consumers provide those meanings and source locations.

## Required consumer inputs

A consumer bootstrap configuration or binding must identify:

```text
consumer repository identity
exact chatgpt-operation revision
expected OS version = Paul
consumer-local authority entry points
durable work-state locator(s)
current-evidence probes/queries
required init skills
optional report additions
```

The central revision must be immutable. A floating ref is invalid for a completed initialization.

## Algorithm

### SB-01 — Resolve consumer binding

Read the consumer-owned binding from current verified repository evidence.

Require one exact `chatgpt-operation` commit SHA.

If the binding is absent, malformed, floating, contradictory, or unreadable:

```text
status = BLOCKED_OPERATING_SOURCE
mutation_authority = false
```

### SB-02 — Verify Paul authority

At the exact revision, read:

```text
docs/operating_system/README.md
docs/operating_system/ESSENTIAL_RULES.md
```

Require the OS registry to identify Paul as ACTIVE.

If the expected version and central registry disagree, fail closed.

### SB-03 — Load only required init skills and index the skill catalog

Load the skill contracts explicitly required by the consumer for initialization.

At the same exact central revision, read the lightweight machine-readable trigger
index:

```text
skills/catalog.json
```

Indexing the catalog is not the same as loading every skill contract. It loads
only names, paths, and trigger metadata so later skill activation does not
depend on chat memory or manual discovery.

Do not preload every central skill merely because it exists.

A missing required init skill or unreadable/malformed central catalog blocks
completed initialization. A mode/action skill that is not currently triggered
remains dormant.

### SB-04 — Restore consumer authority

Read the minimum consumer-local entry sources required to interpret:

```text
repository/domain identity
local semantic authority hierarchy
current work-state ownership
available modes/roles if the consumer uses them
domain-specific evidence/acceptance boundaries
```

Central rules and skills cannot replace these local meanings.

### SB-05 — Restore current state

Inspect current durable repository/process evidence needed to identify the immediate obligation.

Prefer current mutable evidence over stale prose or remembered state.

Reuse exact immutable evidence only after identity verification.

### SB-06 — Identify the first real gate

Classify the earliest unresolved gate that materially blocks the affected path, for example:

```text
OPERATING_SOURCE
AUTHORITY
SEMANTIC_DECISION
DEPENDENCY
PERMISSION
VALIDATION
REVIEW
MERGE
EXTERNAL_WAIT
NONE
```

The consumer may extend this vocabulary.

Do not silently convert uncertainty into a decision.

### SB-06A — Resolve immediate-obligation skill triggers

After current state and the first real gate are known, determine which generic
central trigger(s), if any, apply to the immediate obligation. Consumer-local
routing remains authoritative for domain meaning; central trigger names select
portable mechanics only.

Resolve the trigger(s) against `skills/catalog.json` from the same exact
central revision. Load only the matching skill contract(s) before producing the
init report.

Examples:

```text
current obligation = launch or repair a GitHub Actions execution route
trigger            = GITHUB_ACTIONS_EXECUTION
load               = skills/github-actions-execution/README.md

current obligation = correlate an already-launched Actions run
trigger            = GITHUB_ACTIONS_OBSERVATION
load               = skills/github-actions-observation/README.md
```

This activation is still read-only. Loading a mutation-capable skill does not
grant mutation authority and does not execute the operation.

If an explicitly required trigger cannot be resolved in the exact catalog,
fail closed for the affected action instead of guessing a skill path.

### SB-07 — Report and stop read-only

A successful init report should include at least:

```text
OS = Paul
exact central revision
essential rules loaded
init skills loaded
central skill catalog indexed
trigger(s) resolved for the immediate obligation
triggered skill contracts loaded
consumer repository/ref
current work item/state when applicable
first real gate
evidence uncertainty
recommended consumer-local next mode/action when the consumer defines one
```

Initialization ends read-only.

It does not automatically execute the recommended next action.

## Composition

Typical Paul init:

```text
session-bootstrap
  -> state-refresh when delta/fingerprint planning is applicable
  -> consumer-local routing/semantic interpretation
```

The init cycle may also trigger-load the exact skill needed for the immediate
next obligation after current state is known:

```text
GITHUB_ACTIONS_EXECUTION   -> github-actions-execution
GITHUB_ACTIONS_OBSERVATION -> github-actions-observation
MUTATE                     -> repository-mutation
GOVERNED_WORK              -> governed-work
SCHEDULED_CONTROLLER       -> state-refresh + controller-throughput + controller-lifecycle
```

Other cataloged skills remain dormant until their trigger applies. Trigger-load
during init means "ready to use after init", not "execute during init".

## Safety invariants

- obey Paul ER-01 through ER-09;
- never use chat memory as a substitute for unresolved durable authority;
- never replace an exact pin with a floating ref;
- never grant mutation authority merely because initialization succeeded;
- never infer domain/scientific acceptance from a central skill result;
- never require historical operating metrics to complete Paul initialization.

## Retry behavior

Re-running initialization is safe because the skill is read-only.

A repeated invocation may reuse verified exact immutable central content while refreshing consumer mutable evidence as required by `state-refresh` and the consumer contract.
