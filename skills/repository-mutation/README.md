# repository-mutation

Portable deterministic repository mutation skill.

## Supported v1

| Resource | Actions |
|---|---|
| file | create, update, delete |
| branch | create |

All other resource/action pairs fail closed.

## Retry semantics

Desired post-state is recognized before stale identity rejection:

- create + matching content → `NO_MUTATION_NEEDED`
- update + matching content → `NO_MUTATION_NEEDED`
- delete + target absent → `NO_MUTATION_NEEDED`
- branch create + desired head already present → `NO_MUTATION_NEEDED`

This makes retry safe after remote success followed by local result-persistence failure.
