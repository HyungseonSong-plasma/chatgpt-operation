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
