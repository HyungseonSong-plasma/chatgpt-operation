# Documentation semantic QA — two independent gates v0.1 (experimental)

**Scope:** documentation-consistency skill candidate in Samuel Draft PR #252.
Read-only design; no consumer pin change, badge adoption, protected-branch change
or authorization to merge. This document does not replace the evidence-coverage
v0.2 contract or presentation-only v0.1 contract.

## State model and responsibilities

| | Gate 1: Automated verification | Gate 2: Independent approval |
| --- | --- | --- |
| Owner | Deterministic Samuel checks on caller-provided, pinned source | Independent domain/architecture reviewer |
| Input | Consumer repository, exact SHA, claim scope, required check IDs, exact Git blob content and SHA | Source identity, exact SHA, reviewed scope, Gate 1 report, independent reviewer identity and recorded review decision |
| Status | `SCOPED_CHECKS_PASS` or `REVIEW_REQUIRED` | `REVIEW_REQUIRED`, `APPROVED` or `REJECTED` in a **separately authenticated review record** |
| Meaning | All selected machine predicates matched supplied, blob-bound bytes | A reviewer accepted the bounded meaning and limitations of the claim |
| Cannot prove | End-to-end runtime semantics, complete source inventory, actual GitHub source authenticity, independent judgment | Historical facts outside reviewed scope or entire codebase correctness |

The status vocabularies are **orthogonal**. Gate 1 PASS MUST NOT imply Gate 2
APPROVED. Gate 2 approval MUST NOT override a Gate 1 failure. The overall
governance acceptance requires BOTH gates for the **same consumer repository,
exact source revision and bounded claim scope**. A new current source revision
invalidates a prior approval unless reviewed acceptance explicitly binds it.

### Gate 1 — supported machine predicates

`chatgpt_operation.documentation.semantic_gates_v01.verify_automated_gate_v01`
supports two deliberately limited static properties:

- `JSON_POINTER_EQUALS`: parse caller-supplied JSON and confirm an exact
  string value at a specified JSON pointer. For example,
  `/$id = urn:codeqa:ccg:graph:v0.1`.
- `PYTHON_IMPORT_ABSENT`: parse caller-supplied Python AST and check the
  absence of a specified absolute module-prefix import. Relative imports
  fail closed without the surrounding package context. This is not a
  runtime dependency guarantee.

Each check must supply `kind`, `repository`, `revision`, `scope`,
`path`, `blob_sha`, `content`, `subject`, and an `expected` string
for JSON checks. The checker recomputes the canonical Git SHA-1 blob hash from
the UTF-8 source bytes and refuses missing/extra checks, unsafe paths,
mismatched hashes and unsupported predicates. All required IDs must be
explicitly declared. Caller-provided source is **not** authenticated by this
pure function; the caller must pin and retrieve it through a trusted repository
source and confirm the revision context separately.

Result example:

```json
{
  "status": "SCOPED_CHECKS_PASS",
  "check_results": {"ccg_id": "PASS"},
  "semantic_certification": "NOT_EVALUATED",
  "independent_approval": "REVIEW_REQUIRED"
}
```

`SCOPED_CHECKS_PASS` means only that all declared checks were evaluated and
satisfied. It must not be renamed generic `SEMANTIC_PASS`.

### Gate 2 — review and authority

An authenticated independent reviewer must inspect the original claim,
specified source/contract tests, limitations, revision ancestry and relevant
rendered documentation. The review's **record** (not caller-attested
`independently_verified=True`) must include a real review source URL,
repository, commit SHA, scope, reviewer identity and explicit decision.
The consumer owner defines acceptable reviewer independence and how to
handle historical ADRs. A comment, CI success, successful Git blob comparison,
or self-review is **not** approval.

Gate 2 is intentionally **not implemented as a caller-supplied Boolean or a
user-constructible APPROVED result** in the automated Python check. It remains
`REVIEW_REQUIRED` until a separately authenticated review workflow records
and verifies approval. This separation prevents fabricated check inputs from
promoting review statuses.

## Bounded codeQA pilot

At codeQA PR #289 exact HEAD
`24040c02ea97056de89c6711e847b4f727fb0dcb`:

- A JSON contract ID check can assert the CCG graph schema's declared `$id`;
  it cannot establish architectural quality.
- The source pipeline byte identity and ADR 0001 origin were observed in
  [the pinned evidence report](codeqa-cross-repository-evidence-pilot-20261106.md).
- No independent review approval was observed; do not set `REVIEWED` or mark
  `authority_review` complete.
- The codeQA Samuel pin remains `c803cd6b77c6d112df33d8679bac32f993a658b0`.
- Existing historical decision status is retained; current implementation
  completeness is still `NOT_EVALUATED`.

## Acceptance checks

Gate 1 can proceed autonomously for a **declared subset of source properties**,
but the full semantic architecture claim remains outside its proof scope.
Gate 2 must produce an authenticated independent review record. User-facing
reporting should highlight only failed automated checks, unresolved semantic
questions, and decisions that actually need human approval.

Do not merge PR #252, update the consumer pin, or close PR #289 based solely
on this pilot or on a green CI run.
