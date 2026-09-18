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
