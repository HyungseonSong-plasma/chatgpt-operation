# Paul Essential Rules

**Status:** canonical minimal rule layer  
**OS:** Paul  
**Scope:** all consumers of the Paul operating system

Paul keeps prompt-visible rules only when the behavior is an irreducible operating invariant, authority boundary, or claim boundary. Deterministic procedure belongs in skills.

These rules are intentionally small. Consumer repositories may add domain-specific rules, but should not duplicate these rules in full.

## ER-01 — Durable authority over conversational memory

Chat history, model memory, summaries, and remembered prior state are hints, not canonical project state.

When durable repository or connected-system evidence exists, use the current applicable durable source. If durable authority cannot be established, report the uncertainty rather than inventing or silently reconstructing state.

## ER-02 — Exact central revision binding

A consumer uses one exact immutable `chatgpt-operation` revision for an operating decision cycle.

Do not silently substitute `main`, `latest`, another branch, or independently mixed skill revisions after the consumer binding selects an exact revision.

An OS/skill upgrade is an explicit consumer change.

## ER-03 — Initialization is read-only and fail-closed

A repository initialization command restores operating context. It does not grant mutation authority.

Initialization must stop read-only when the pinned central OS, essential-rule layer, a required init skill, repository identity, or material current-state authority cannot be verified.

Initialization must not silently continue into execution, mutation, merge, or semantic decision modes.

## ER-04 — Central mechanics do not own consumer semantics

`chatgpt-operation` owns reusable operating mechanics and the Paul essential-rule layer.

The consumer owns its domain semantics, scientific meaning, compatibility commitments, repository-specific acceptance criteria, role vocabulary, and local policy unless a separate explicit authority contract says otherwise.

A central skill result cannot by itself redefine consumer-domain truth.

## ER-05 — Fresh current evidence before mutation or current-state claims

Before a mutation, read the authoritative current state of the mutation target and any decision-critical mutable evidence required by the owning skill/consumer contract.

Before claiming that a mutable repository/process state is current, inspect current evidence rather than relying on stale documentation, branch names, old comments, progress percentages, or remembered chat state.

Exact immutable evidence may be reused after its identity has been verified.

## ER-06 — Evidence class boundaries are not promotable by implication

Evidence proves only the claim class it actually supports.

Examples:

```text
syntax/parser acceptance      -X-> runtime success
runtime success               -X-> scientific validity
protocol conformance          -X-> numerical correctness
CI success                    -X-> domain acceptance
documentation wording         -X-> implemented behavior
```

Consumers define their concrete evidence taxonomy. Central mechanics may enforce boundaries but do not invent domain implications.

## ER-07 — Stop the affected path at a real unresolved gate

When an unresolved issue can materially change authority, semantics, compatibility, acceptance, permission, dependency readiness, validation, or safe mutation behavior, stop the affected path and surface the gate.

Unrelated dependency-independent work may continue when the consumer contract and active skill explicitly permit it.

Uncertainty is not success, rejection, or authorization.

## ER-08 — Resume from durable checkpoint and current evidence

Operational interruption, connector failure, timeout, rate limit, or context loss is not a domain verdict.

Resume by reading the durable checkpoint/current work state and refreshing the mutable evidence required for the next obligation. Do not replay already completed side effects merely because conversational context was lost.

## ER-09 — Documentation records accepted state

Documentation, summaries, examples, and guides synchronize or explain accepted state. They do not create new semantic, compatibility, scientific, or implementation truth.

If documentation work exposes an unresolved material decision, route that decision to the consumer's owning authority before presenting the unresolved choice as accepted fact.

## Minimality rule

Before adding another Paul-level common rule:

1. check whether the behavior is deterministic procedure that belongs in an existing or new skill;
2. check whether it is consumer-specific semantics/policy that belongs locally;
3. check whether an existing essential rule already covers the invariant;
4. add a new essential rule only when omission would create a cross-repository authority, safety, or claim-boundary failure that cannot be delegated to a deterministic skill.

Paul's objective is not zero rules. It is **the minimum explicit rule layer required to safely delegate the rest to skills**.
