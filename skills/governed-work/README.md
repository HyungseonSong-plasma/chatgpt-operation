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


## Stage capability dependency invariant

Ordered stages are not merely labels. Before execution, a manifest author/controller MUST establish a producer-before-consumer dependency order for runtime capabilities and artifacts.

Canonical lifecycle:

```text
source/static validation
  -> build or restore required executable/artifact
  -> executable/runtime capability probe
  -> runtime experiment
  -> evidence analysis
```

A stage that consumes a capability or artifact MUST NOT precede the stage that produces, restores, or qualifies it. Examples include:

- invoking `physics-opt --help` requires `physics-opt` to exist first;
- probing a native profiler requires a built/restored executable first;
- runtime preflight requiring generated inputs must follow input generation;
- analysis requiring runtime evidence must follow the producing run.

Manifest planning should express or verify `requires` / `produces` relationships when such dependencies exist. If an existing manifest format cannot encode them directly, the controller must still validate the dependency DAG before launch and order serial prepare stages accordingly.

A detected producer-after-consumer ordering is:

```text
INVALID_STAGE_ORDER
classification = INFRASTRUCTURE_HARNESS_FAILURE
scientific_result = UNRESOLVED
```

The repair obligation is limited to the owning harness/manifest ordering. It MUST NOT change scientific equations, tolerances, convergence criteria, timestep hierarchy, controls, or acceptance thresholds to obtain a green run.

This check occurs before expensive runtime execution whenever the dependency is statically knowable.


### Non-mutating capability probe invariant

A capability-probe/inspection stage that consumes an already qualified producer artifact MUST be observational by default.

```text
producer/build -> qualified artifact -> read-only capability probe
```

The probe MUST NOT implicitly rerun the producer/build, regenerate its workspace, delete producer outputs, or mutate producer-owned cache/output directories merely to inspect the artifact. In particular:

```text
probe != rebuild
probe != regenerate
probe != cleanup producer workspace
```

If a probe needs a different artifact state, that state requires an explicit producer stage and dependency edge. A probe-side rebuild or cleanup failure is `INFRASTRUCTURE_HARNESS_FAILURE`; the scientific result remains `UNRESOLVED`. Repair the harness ownership/ordering only.
