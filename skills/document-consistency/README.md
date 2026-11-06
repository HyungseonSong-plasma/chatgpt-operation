# Documentation Consistency QA v0.1 — static status badges

**OS:** Samuel · **Activation:** `DOCUMENTATION_CONSISTENCY_QA` (on demand)  
**Contract:** [v0.1](contract-v0.1.json) · **Mode:** read-only

## Purpose

Define a reusable **rounded single-piece local SVG** status presentation across repositories and check whether each document's three displayed labels agree with its caller-declared metadata and local badge asset bytes. This is intentionally narrower than semantic documentation consistency or a code/runtime correctness oracle. It does **not** infer adopted design, implementation completeness, or review approval from source files, issue closure, or CI.

## Orthogonal status axes

| Axis | Values | Interpretation |
| --- | --- | --- |
| Decision | `PROPOSED`, `ADOPTED`, `SUPERSEDED`, `NOT_EVALUATED` | A consumer-owned design decision; adopted is not implemented |
| Implementation | `IMPLEMENTED`, `PARTIAL`, `NOT_IMPLEMENTED`, `NOT_EVALUATED` | Bounded consumer-declared state, not inferred by the badge tool |
| Review | `REVIEWED`, `REVIEW_REQUIRED`, `NOT_EVALUATED` | Provenance-sensitive human/domain review state, not asserted by this tool |

Colors: adopted/implemented/reviewed `#2DA44E` (green); proposed `#0969DA` (blue); partial/review required `#BF8700` (amber); not implemented `#CF222E` (red); unknown/superseded `#6E7781` (grey). SVGs use a softly tinted background, high-contrast matching text, a subtle border, 11 px rounded corners and a 22 px height. Only the status appears visibly inside each chip; its axis and full status remain available in image alt text and SVG title. This mirrors the chat badge presentation more closely than a split, flat-square Shields-style badge. Local SVG assets eliminate third-party badge availability and network tracking dependencies; a matching SVG proves the *presentation*, not the underlying status.

**All three labels must appear immediately after the document's first Markdown H1.** Use this approach for documentation managed by the consumer's labeling policy; migrate existing documents progressively, with unverified values recorded as `NOT_EVALUATED`.

## Portable Python interface

```python
from chatgpt_operation.documentation.status_labels import (
    badge_filename, render_badge_svg, render_badge_header,
    audit_document_labels,
)

labels = {
    "decision": "PROPOSED",
    "implementation": "NOT_EVALUATED",
    "review": "NOT_EVALUATED",
}
# Caller chooses the relative path from each document to its local assets.
header = render_badge_header(labels, asset_dir="../assets/document-status")
# Caller may stage its own local files (never written by this module):
svg = render_badge_svg("decision", "PROPOSED")
asset_name = badge_filename("decision", "PROPOSED")

# Read-only check, using caller-attested exact source inputs:
audit = audit_document_labels(
    markdown=doc_bytes.decode("utf-8"),
    document_path="docs/governance/example.md",
    labels=labels,
    snapshot_sha=exact_commit,
    source_inventory=tracked_paths_at_exact_commit,
    inventory_complete=True,
    badge_sources=local_asset_contents_by_repository_path,
)
assert audit.status == "MATCH"
assert audit.semantic_status == "NOT_EVALUATED"
```

The contract requires all three label dimensions, a 40-character source SHA and complete attested source inventory; it checks exact local SVG assets, label spelling/placement, and palette integrity. `MATCH` is **display integrity only**, never domain approval, verified implementation, or full Markdown/GitHub rendering proof.

The consumer owns the accepted design decision, evidence/claims, implementation status and independent reviewer identity. Keep `declared` distinct from `verified`; never upgrade a label from `NOT_EVALUATED` based only on a green CI result, a closed GitHub issue or the presence of code. When code changes invalidate evidence, flag re-review; do not silently demote or promote adopted history.

## Composition and rollout

`documentation-refinement` remains the existing optional read-only renderer and link/readability auditor. This skill complements it; it does not change the `INIT` set. Source verification, repository reads and actual documentation writes are caller-owned; any write must use the separately authorized Samuel mutation route with fresh branch/HEAD/blob evidence and postcondition checks. Consumers adopt a new central pin only through their own explicit reviewed update.

For codeQA, the initial pilot integrates selected representative header labels and a local consistency check; it is **not** a claim that every historical document has been semantically classified, nor a requirement to move all documents in one PR.

## Explicit two-gate semantic QA (experimental)

[Semantic QA two-gate v0.1](semantic-gates-v0.1.md) is an **optional,
read-only** companion to the presentation-only v0.1 status badge check and
the [evidence coverage v0.2](evidence-coverage-v0.2.md) attestation audit.

- **Gate 1** evaluates explicitly enumerated, revision- and blob-bound
  *machine-checkable* predicates. `SCOPED_CHECKS_PASS` is limited to those
  assertions, not an unrestricted semantic `PASS`.
- **Gate 2** is independent domain/architecture approval with an authenticated
  reviewer decision bound to the same repository, scope and exact revision.
  It remains `REVIEW_REQUIRED` even when Gate 1 passes. No caller Boolean,
  local test success, review comment or GitHub blob equality can confer approval.

The two verdicts MUST remain separate. A consumer may require both for a
governed merge, but a passed Gate 1 must never change a document's Review
badge, certify an adopted architecture, or upgrade a consumer pin automatically.
