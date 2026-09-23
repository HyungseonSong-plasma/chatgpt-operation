# scientific-discriminator-controller

Portable controller skill for iterative scientific and numerical diagnosis with multiple isolated hypothesis lanes.

## Core objective

The consumer provides a durable optimization or diagnosis objective. The controller may formulate several plausible hypotheses in one cycle and validate them in parallel, provided their experiments cannot contaminate one another.

The central pattern is:

```text
fresh evidence
  -> hypothesis set
  -> isolated discriminator lanes
  -> governed execution
  -> lane-local evidence
  -> ACCEPT / REJECT / UNRESOLVED per hypothesis
  -> durable next obligations
```

## Experimental-isolation invariant

Multiple hypotheses are allowed. Their validation processes are independent.

Every experiment lane must:

- start from the same immutable `baseline_sha` for the current generation;
- bind to exactly one hypothesis;
- use a unique mutation branch;
- use a unique workspace/runtime namespace;
- use a unique non-overlapping artifact namespace;
- consume only declared read-only shared baseline inputs;
- never consume another lane's code mutation, runtime artifact, or conclusion;
- declare its mutation scope, controls and discriminating observables before execution.

A result from one lane may motivate a later generation, but it must not silently modify another lane in the same generation.

## Hypothesis contract

Each hypothesis requires:

- statement;
- causal/mechanistic explanation;
- explicit falsifier;
- prior evidence.

A hypothesis is not accepted merely because its experiment completed. Scientific interpretation remains evidence-based.

## Sweeps

Parameter sweeps are allowed inside one hypothesis lane when the variants test the same mechanism and share the same isolated baseline.

A broad sweep with no discriminating hypothesis is not a scientific discriminator plan.

## Consumer objective contract

The plan must state:

- architecture invariant;
- performance/scientific metric;
- target;
- success condition;
- frozen invariants.

These are consumer-owned semantics. The central skill validates structure and isolation, not domain truth.

## Result semantics

Each hypothesis is classified independently:

```text
SUPPORTED
REJECTED
UNRESOLVED
```

A cycle may therefore end with mixed outcomes. No lane is required to wait for a different lane before its evidence can be interpreted.

Promotion or combination happens only in a later, explicit integration/qualification generation. Independent positive lanes must not be combined automatically.

## Composition

Typical scheduled-controller composition:

```text
state-refresh
  -> scientific-discriminator-controller
  -> repository-mutation (per isolated lane)
  -> governed-work / governed-matrix
  -> artifact-staging where needed
  -> github-actions-observation
  -> lane-local interpretation
  -> controller-lifecycle
```

## Initial #310 use

For `moose-test-repo` Issue #310 the consumer objective is:

```text
architecture invariant:
  retain the Gummel iteration structure

metric:
  average fixed-point loops per electron step

target:
  O(10) or lower

success:
  target reached while preserving frozen plasma physics,
  timestep, convergence tolerances and qualified solution parity
```

Candidate hypotheses can be explored in parallel, for example first-Secant-update ordering, transformed-variable ownership/history, or a different Gummel-compatible acceleration strategy. Each receives a separate experiment lane from the same immutable baseline.

## Validator

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli controller validate-discriminator-plan \
  --input discriminator-plan.json
```

Schema: `schemas/scientific-discriminator-controller.schema.json`.
