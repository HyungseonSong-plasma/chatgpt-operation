# Samuel Wake Contract

## Purpose

GitHub Actions events wake Samuel; they do not own Samuel lifecycle truth. The durable admission ledger and StateKernel remain authoritative. The wake boundary may coalesce or replace pending events only when every event admitted into the Bootstrap concurrency group is sufficient to reconstruct the same controller work from repository and durable-state observations.

## Canonical wake paths

| Source | Boundary | Controller meaning |
| --- | --- | --- |
| Issue opened, reopened, or labeled | `Samuel Bootstrap` | Useful edge trigger. Bootstrap rebuilds the bounded repository snapshot and reconciles all open Issues explicitly labeled `samuel`. |
| Ordinary Issue comment | `Samuel Reasoning Wake` only | No Bootstrap wake. The mediator job skips before entering Bootstrap concurrency. |
| Reasoning submission comment containing `<!-- samuel-reasoning-submission -->` | `Samuel Reasoning Wake` -> `workflow_dispatch` of `Samuel Bootstrap` | The comment is durable GitHub input; the forwarded Bootstrap run is a generic reconciliation wake. |
| Schedule | `Samuel Bootstrap` | Generic reconciliation wake. |
| Explicit continuation / operator dispatch | `Samuel Bootstrap` | Generic reconciliation wake. |
| Worker terminal persistence | current Bootstrap composition root -> explicit Bootstrap `workflow_dispatch` | Continue from the newly persisted StateKernel revision; no second lifecycle queue is created. |

## Serialization and coalescing

`Samuel Bootstrap` keeps one repository-wide concurrency group, `samuel-bootstrap`, with `cancel-in-progress: false`. Already-running controller work is never intentionally cancelled by this contract.

GitHub may coalesce or replace pending runs in one concurrency group. That is safe only because runs admitted to the Bootstrap group are useful reconciliation wakes. Each one rebuilds the current repository snapshot and calls controller admission reconciliation before selecting work. Therefore loss of a particular Issue event does not lose an actionable opt-in when a later useful wake survives: the surviving wake observes the same open, explicitly labeled Issue and deterministically reconstructs its ledger entry.

Comment filtering is deliberately outside the Bootstrap concurrency group. An unrelated comment must never occupy or replace the only pending Bootstrap wake and then skip at the Bootstrap job level.

## Authoritative truth and idempotence

Wake order is not lifecycle history. Samuel derives work identity and status from:

1. the durable admission ledger;
2. the durable StateKernel;
3. bounded current repository observations used for reconciliation and preflight.

`discover_admissible_issues()` performs deterministic, ordered upsert of open Issues carrying the explicit `samuel` label. Replaying a useful wake against unchanged durable state and repository observations is therefore a no-op for admission truth and selects the same next controller work.

The reasoning-comment mediator has no Issue-write or StateKernel-write authority. Its only side effect is forwarding an accepted marker comment to the Bootstrap `workflow_dispatch` boundary.

## Failure boundary

The controller remains fail-closed when durable state is malformed, admission identity changes, or required repository context is structurally invalid. Wake reconciliation does not authorize overwriting StateKernel ownership, bypassing lifecycle guards, or inventing work from unlabeled Issues.

The bounded repository snapshot is not an unbounded event journal. If future repository scale exceeds an observation bound, that bound must be handled explicitly rather than turning wake history into a second source of truth.

## Non-goals

This contract does not add a wake queue, event log, or secondary lifecycle store. It does not change StateKernel ownership rules, pre-dispatch recovery semantics, or the controller's acceptance-criterion selection. Those remain separate control-plane concerns.
