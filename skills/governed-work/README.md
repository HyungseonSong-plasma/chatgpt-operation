# governed-work

Portable deterministic execution for checked-in experiment/refactor manifests.

## Owns

- closed-world manifest parsing;
- issue/kind/sequence dispatch binding;
- exact workspace SHA binding;
- ordered stage execution without a shell;
- timeouts and nonzero-exit classification;
- deterministic stage logs;
- repository-relative artifact collection;
- structured `evidence.json`;
- monotonic manifest skeleton allocation.

## Does not own

- consumer GitHub workflow names;
- consumer permissions/concurrency;
- consumer package architecture;
- scientific interpretation of successful runtime output;
- repository mutation.

Consumers should pin the composite action to an exact commit SHA.
