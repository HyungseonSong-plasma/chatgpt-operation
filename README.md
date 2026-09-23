# chatgpt-operation

Canonical source for ChatGPT operating-system version management and reusable deterministic operating skills.

## Operating system

Named operating-system baselines and successor lifecycle are owned here:

```text
docs/operating_system/README.md
```

Current named baseline: **Paul** (2026-09-20) — the **Rule-Minimal / Skill-Optimized** generation.  
Historical predecessor: **Calvin** — the **Rule-Optimized** generation.

The generation transition is architectural:

```text
Calvin
  -> optimize which prompt-visible rules are active

Paul
  -> minimize prompt-visible rules
  -> delegate reusable deterministic mechanics to tested/versioned skills
  -> keep only irreducible semantic, authority, and trigger contracts as rules
```

Paul is ACTIVE. Its canonical minimal common rules live in `docs/operating_system/ESSENTIAL_RULES.md`; the extraction from current consumer repositories is recorded in `docs/operating_system/COMMON_RULE_EXTRACTION.md`.

Consumer repositories bind to one exact immutable `chatgpt-operation` revision for an operating decision cycle. The central repository owns OS identity/lifecycle, the essential common rule layer, and reusable mechanics; consumers retain domain semantics, repository-specific policy, scientific/compatibility meaning, and local acceptance criteria.

Calvin-era operating metrics for rule/application efficiency are archival only under Paul. They are not required for initialization, routing, or acceptance.

## Session bootstrap

Paul centralizes generic new/resumed-session initialization in:

```text
skills/session-bootstrap/README.md
```

The portable sequence is:

```text
exact consumer binding
  -> verify Paul
  -> load Paul essential rules
  -> load required init skills
  -> index central skills/catalog.json trigger metadata
  -> restore consumer-local authority and current state
  -> identify first real gate and immediate obligation
  -> trigger-load only the matching skill contract(s)
  -> report ready-to-use skill context and stop read-only
```

Consumer repositories supply only their local authority entry points, state/evidence locators, and required skill triggers.

## Repository mutation v1

The first packaged skill is portable repository mutation.

```text
LLM / caller
  -> chooses semantic intent

consumer repository
  -> owns policy, manifest, permissions, triggers, and workflow concurrency

chatgpt-operation
  -> owns deterministic mutation mechanics and the private composite action
```

Portable v1 intentionally supports only:

- file create/update/delete through GitHub Contents API SHA semantics;
- branch create through expected absence.

Branch move/delete and issue/PR mutations are not part of v1.

### GitHub Actions

Consumer workflows pin this private action to an exact commit SHA:

```yaml
- uses: HyungseonSong-plasma/chatgpt-operation/.github/actions/repository-mutation@<exact-sha>
  with:
    manifest: automation/mutations/example.json
    policy: .chatgpt-operation.json
    repository: ${{ github.repository }}
    github-token: ${{ github.token }}
    current-run-id: ${{ github.run_id }}
```

The central repository must allow the consumer under **Settings → Actions → General → Access**.

### Local use

v1 publishes no wheel and has no third-party Python runtime dependencies.
Use an authenticated checkout of this canonical repository at an exact commit SHA:

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli source verify \
  --repository HyungseonSong-plasma/chatgpt-operation \
  --expected-sha <exact-sha>
```

### Security contract

- closed-world resource/action surface;
- consumer path and branch authorization;
- deny overrides allow; unmatched targets are denied;
- exact repository binding;
- retry-safe desired-post-state recognition;
- deterministic operation ID;
- complete pagination of validation-gate Actions runs;
- incomplete enumeration fails closed;
- read-back verification after write;
- structured failure results;
- no force/history-rewrite surface.

## Governed work v1

The second portable skill owns deterministic checked-in work manifests and their execution.

```text
consumer repository
  -> owns workflow entrypoints, permissions, checked-in manifests, and repo-specific guards

chatgpt-operation
  -> owns manifest parsing, dispatch identity validation, stage execution,
     timeout/nonzero handling, logs, artifact collection, and evidence.json
```

GitHub Actions consumers pin:

```yaml
- uses: HyungseonSong-plasma/chatgpt-operation/.github/actions/governed-work@<exact-sha>
  with:
    kind: experiments
    manifest: ${{ github.workspace }}/control/automation/manifests/experiments/Issue_123_experiments01.json
    control-root: ${{ github.workspace }}/control
    workspace: ${{ github.workspace }}/workspace
    base-sha: <exact-workspace-sha>
    issue: 123
    sequence: 1
    results: ${{ github.workspace }}/results
```

Local manifest scaffolding is available from an exact checkout of this repository:

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli work new \
  --issue 123 --kind experiments --title "Example"
```

The portable core intentionally knows nothing about a consumer's GitHub workflow filenames or package architecture. Those remain consumer-local guards.

## Controller lifecycle v1

The third portable skill prevents scheduled work controllers from disabling
because of a single empty or incomplete repository observation.

```text
caller/controller
  -> collects repository evidence using consumer-specific queries
  -> persists prior terminal candidate in a durable checkpoint

chatgpt-operation
  -> evaluates lifecycle deterministically
  -> never treats one empty scan as completion
  -> requires two independent work scans
  -> requires sentinel + active-work terminal witnesses
  -> requires a later controller cycle to confirm completion
```

Only `VERIFIED_COMPLETE` (or explicit `PAUSED`) returns
`can_disable=true`. Tool/query uncertainty and malformed evidence must be
handled by callers as **no-disable** conditions.

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli controller evaluate \
  --input controller-snapshot.json

PYTHONPATH=src python3 -m chatgpt_operation.cli controller self-test
```

See `skills/controller-lifecycle/README.md` for the snapshot and scheduler
integration contract.


## Controller throughput v1

The fourth portable skill prevents scheduled controllers from wasting cycles on
mechanical serialization and broken validation routes.

```text
one invocation
  -> synchronize durable authority
  -> repair missing validation route instead of waiting
  -> execute a bounded synchronous work burst
  -> use dependency-independent lanes under scoped locks
  -> stop at the first real external wait boundary
```

A required exact-head validation with zero runs is classified
`MISSING_VALIDATION_ROUTE`, not `WAIT_EXTERNAL`.

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli controller throughput \
  --input controller-throughput.json

PYTHONPATH=src python3 -m chatgpt_operation.cli controller throughput-self-test
```

See `skills/controller-throughput/README.md` for the portable contract.


## State refresh v1

The fifth portable skill makes controller fresh-read scope deterministic and
delta-based without weakening mutation-time authority checks.

```text
durable checkpoint
  -> cheap mutable fingerprints
  -> expand only changed decision-critical surfaces
  -> skip verified exact immutable pins
  -> authoritative prewrite read for every mutation target
```

Checkpoint uncertainty, phase/rule/scope changes, contradictory evidence, or an
unknown next action escalate to `FULL_REFRESH_REQUIRED`. Probe failures block
instead of silently falling back to stale state.

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli controller state-refresh \
  --input state-refresh.json

PYTHONPATH=src python3 -m chatgpt_operation.cli controller state-refresh-self-test
```

See `skills/state-refresh/README.md` for the portable contract.


## GitHub Actions observation v1

The trigger-loaded `github-actions-observation` skill provides deterministic
GitHub Actions run correlation plus a portable Python dispatch/observe runtime.

```text
workflow_dispatch request
  -> optional direct workflow_run_id receipt
  -> exact run observation
  -> deterministic MATCHED_ACTIVE / MATCHED_TERMINAL / fail-closed status
```

It supports non-default branch/tag refs while preserving GitHub's requirement
that a dispatchable workflow be registered on the default branch. Execution
success remains execution evidence only and does not imply scientific validity
or consumer acceptance. See `skills/github-actions-observation/README.md`.

For ChatGPT-hosted GitHub connectors, issue #31 defines a credential-free
workflow-dispatch action contract and response normalization in
`src/chatgpt_operation/github/connector_dispatch.py`. This repository does not
own the connector-held credential or the host's callable tool inventory.


## GitHub Actions execution v1

The trigger-loaded `github-actions-execution` skill selects a safe execution
route without treating `workflow_dispatch` as an implicit requirement.

```text
required execution claim
  -> fresh route capabilities
  -> deterministic sufficiency filter
  -> direct dispatch / existing trigger / rerun / one-shot
  -> repository-mutation handoff when needed
  -> github-actions-observation
  -> cleanup obligation for one-shot routes
```

A missing preferred mechanism is not a missing execution route. Event identity
is preserved only when the event itself is part of the required claim. See
`skills/github-actions-execution/README.md`.

## Characterized ownership migration

The trigger-loaded `characterized-ownership-migration` skill defines reusable cutover and retirement gates for accepted ownership refactors.

```text
owner/caller census
  -> source-contract characterization
  -> target readiness
  -> bounded migration
  -> parity
  -> canonical caller cutover
  -> zero-source-caller proof
  -> retirement
  -> exact-head validation
```

It is intentionally domain-agnostic: it does not decide scientific semantics, backend realization policy, compatibility commitments, or architecture desirability. See `skills/characterized-ownership-migration/README.md`.

## Governed matrix v1

The sixth portable skill centralizes build-once / fan-out / fan-in experiment execution.

```text
consumer matrix manifest
  -> central plan validation
  -> governed prepare/build once
  -> mode-preserving tar bundle
  -> independent matrix runners
  -> optional aggregate over case evidence
```

Consumers call `.github/workflows/governed-matrix.yml` at an exact immutable central SHA and pass the same SHA as `operation_sha`. See `skills/governed-matrix/README.md`.
