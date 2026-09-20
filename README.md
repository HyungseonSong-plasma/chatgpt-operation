# chatgpt-operation

Central source for reusable deterministic ChatGPT operating skills.

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
