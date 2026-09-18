# chatgpt-operation

Central repository for reusable ChatGPT operating skills, policies, and reviewable automation contracts.

## Repository mutation v1

The first packaged skill is repository mutation.

Portable v1 supports only operations whose conflict behavior can be made safe without treating a preflight Actions check as a repository lease:

- file create/update/delete through the GitHub Contents API;
- branch create.

Portable v1 intentionally does **not** support branch move/delete or issue/PR mutation.

GitHub Actions consumers use the private composite action at an exact immutable commit SHA from a consumer-local workflow. The consumer workflow owns triggers, permissions, concurrency, and repository-specific authorization policy.

The central action executes code bundled in the same immutable action revision; mutation-target input must never select executable control-plane code.

The implementation branch remains staging until the CodeRabbit/Greptile review in `moose-test-repo` is dispositioned.

## Consumer policy

Portable v1 requires a consumer-owned TOML authorization policy. Unknown fields fail closed.

```toml
schema_version = 1
repository = "owner/repository"

[mutation]
protected_branches = ["main"]
allow_file_mutation_on_protected = false

[mutation.allow]
file = ["create", "update", "delete"]
branch = ["create"]

[validation_gate]
mode = "all_actions"
workflows = []
ignore_current_run = true
```

The validation gate is a point-in-time execution gate, not a repository lease. Mutation conflict safety comes from the supported GitHub write primitives, not from assuming the gate excludes every other writer.
