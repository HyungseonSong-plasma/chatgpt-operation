# Scientific semantics centralization

Samuel's control plane owns portable scientific semantics. Consumer repositories
own solver-specific realization and runtime.

## Ownership boundary

Promoted into `chatgpt-operation`:

- immutable scientific state, evidence, hypothesis, claim, capability, action and policy records;
- deterministic `ScientificPolicy` synthesis;
- solver-independent `ExecutionPlan` compilation;
- machine-readable scientific execution-contract mechanics;
- reference-only run provenance envelopes;
- evidence-driven runtime error attribution.

Remain consumer-owned in `moose-test-repo`:

- `physics_harness.adapters.moose/**`;
- executable discovery and MOOSE process runtime;
- numerical evidence stores and MOOSE-specific queries;
- input lowering, Physics application gateway and repository CI;
- target workflows `experiment.yml` and `refactor.yml`.

## Migration state machine

```text
moose-test-repo qualified implementation
        |
        v
centralized
        |
        | exact canonical revision selected
        | consumer compatibility proof
        | consumer CI success
        v
consumer_cutover
        |
        | zero remaining local imports
        v
retirement_ready
        |
        | mutation authorized by consumer .chatgpt-operation.json
        v
retired
```

Promotion alone never authorizes deletion.

The machine-readable source of truth is
`automation/samuel/scientific-centralization.json`. Samuel reasoning may read
this contract. A duplicate can become a deletion candidate only when both the
component phase is `retirement_ready` and that consumer is
`cutover_verified`.

## Origin

The initial canonical implementation was promoted from
`HyungseonSong-plasma/moose-test-repo@3c6e91a039600ceb4c152c8fd787e03160ad7c72`.

The next migration step is consumer cutover. It must establish an exact-revision
distribution/import mechanism before any duplicate module is removed.
