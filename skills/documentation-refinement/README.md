# documentation-refinement

**OS:** Samuel · **Activation:** `DOCUMENTATION_REFINEMENT` (on demand)  
**Machine contract:** [v0.2](contract-v0.2.json) · [v0.1](contract.json) (legacy compatible)  
**Runtime:** `chatgpt_operation.documentation.refine_document`

## Purpose

Refine repository documentation without silently changing its meaning or
taking ownership of consumer-specific facts. This is a reusable
**document transformation and validation** skill, not a document authority
or an autonomous GitHub writer.

## Workflow

```text
accepted document request + exact repository snapshot
  -> DISCOVER: validate caller's source inventory
  -> UNDERSTAND: map each description to source evidence
  -> STRUCTURE: build a typed document model
  -> COMPACT: normalize whitespace without dropping entries
  -> DESIGN: render minimal or fastapi-astro Markdown (+ optional source-witnessed Mermaid)
  -> VALIDATE: v0.1 links/claims + v0.2 anchors/readability audit
  -> DELIVER: hand proposed text to Samuel repository-mutation
```

The caller performs actual repository reads and interpretation. The
deterministic Python runtime **does not** fetch files, discover a repository,
infer code semantics, write files, dispatch workflows, or merge PRs.
It rejects incomplete source inventories and unwitnessed entries rather
than claiming an exhaustive or semantically verified rewrite.

## Input contract

The caller provides:

- An **exact 40-character source commit SHA**, a complete, explicitly attested
  source-path inventory and the target document's repository-relative path.
- A typed document description with title, tagline, introduction, sections,
  and entries. Each entry has a label, local/external link, short purpose and
  an **inventory-backed evidence path**.
- The original Markdown as `baseline_markdown`, plus explicitly chosen
  `required_claims` that must remain visible.
- A design preset: `minimal` or `fastapi-astro`.

A witness path establishes provenance of a proposed description, **not**
its semantic truth. Consumer domain owners must inspect the accuracy of claims,
eligibility of omissions and any architectural/policy implications.

## Programmatic use

```python
from chatgpt_operation.documentation import refine_document

result = refine_document(
    payload={
        "snapshot_sha": "<40-character commit SHA>",
        "document_path": "contracts/README.md",
        "title": "Contracts",
        "tagline": "Schemas describe structure; profiles select policy.",
        "introduction": "Versioned exchange contracts.",
        "sections": [{
            "key": "adapters",
            "title": "Adapters",
            "subtitle": "Language integration",
            "entries": [{
                "label": "Capability",
                "href": "adapters/capability-v0.1.schema.json",
                "description": "Declared adapter support and limits.",
                "evidence_path": "contracts/adapters/capability-v0.1.schema.json",
            }],
        }],
        "closing": "New areas require accepted design.",
    },
    source_inventory=[
        "contracts/README.md",
        "contracts/adapters/capability-v0.1.schema.json",
    ],
    inventory_complete=True,
    baseline_markdown="[Capability](adapters/capability-v0.1.schema.json)\nDeclared adapter support and limits.",
    required_claims=["Declared adapter support and limits."],
    preset="fastapi-astro",
)
print(result.markdown)  # Candidate only: no GitHub mutation.
```

`RefinementError` means a deterministic gate failed. The result includes
the source SHA, chosen preset, and preservation checks. The baseline-to-output
link test covers Markdown links and simple HTML hrefs, not every GitHub-Flavored
Markdown feature. Run a GitHub rendering review and all consumer-specific
documentation checks before acceptance.

## v0.2 Markdown quality gates

The **v0.1 document model and `refine_document()` API remain supported**.
Before a consumer hands any candidate to Samuel repository mutation, run the
separate read-only v0.2 audit against the exact baseline text:

```python
from chatgpt_operation.documentation import (
    ReadabilityBudget, audit_markdown_v02,
)

audit = audit_markdown_v02(
    original_markdown,
    candidate_markdown,
    budget=ReadabilityBudget(
        max_character_growth_ratio=1.8,
        max_line_growth_ratio=1.8,
        max_table_row_chars=240,
    ),
)
if not audit.passed:
    raise ValueError(f"documentation review required: {audit.issues}")
```

The audit verifies **target multiplicities of baseline links**, detects
lost Markdown heading anchors (including repeated headings), checks local
`#fragment` links, and enforces explicit document-growth and table-row
budgets. The result lists missing anchor IDs and link targets, and reports
line/character counts and maximum table-row length.

**Important:** raw HTML `<h1>` headers are *not* assumed to preserve the
GitHub-generated slug of a previous Markdown `# Heading`. A deliberate
compatibility alias such as `<a name="old-slug"></a>` may be accepted by
the checker, but its repository write still requires its own authorized
mutation. Do not bypass any upstream write-safety block.

This is a **conservative Markdown subset**, not a complete GitHub-Flavored
Markdown renderer/parser or a proof of semantic equivalence. Use actual GitHub
rendering review for unsupported syntax and external deep-link assumptions.
Budgets can be adjusted only with a documented consumer/human justification
(e.g., a short index legitimately expanding to catalog all contracts);
a waiver must not disable semantic review or bypass a denied repository write.

The audit itself never writes files, authorizes a PR, or merges it. Under
v0.2 the published [machine contract](contract-v0.2.json) documents both
the legacy generator and the new optional-read-only validator, with the
validator required for newly requested v0.2 document transformations.

## v0.2 README structure and concept diagrams

Issue [codeQA #282](https://github.com/HyungseonSong-plasma/codeQA/issues/282)
also calls for structural and conceptual diagrams. The optional
`refine_document(..., diagram=...)` argument generates **GitHub-native
Mermaid** within the proposed Markdown. It introduces no raster assets,
external rendering service, JavaScript, GitHub writes or diagram-inferred
architecture facts.

The caller must supply a **bounded typed relationship graph**. Nodes and
edges need individually declared source-evidence paths present in the
attested exact-SHA inventory; adjacency is not inferred from filenames.
For example (using the existing `refine_document` call shown above):

```python
diagram = {
    "title": "Contracts and adapters",
    "caption": "Conceptual contract ownership declared by the caller.",
    "nodes": [
        {"id": "schema", "label": "Contract schema",
         "evidence_path": "contracts/adapters/capability-v0.1.schema.json"},
        {"id": "adapter", "label": "Adapter capability",
         "evidence_path": "contracts/adapters/capability-v0.1.schema.json"},
    ],
    "edges": [
        {"source": "schema", "target": "adapter",
         "label": "describes shape of",
         "evidence_path": "contracts/adapters/capability-v0.1.schema.json"},
    ],
}
# Pass diagram=diagram alongside the earlier call's existing arguments.
```

The renderer emits a deterministic `flowchart LR` with **quoted escaped
labels**, a textual caption, a sorted source-witness list and an explicit
"not runtime/semantic proof" caveat. It rejects unsafe node IDs,
undeclared endpoints, unsupported keys, missing evidence, duplicates,
control characters and oversized graphs (2–24 nodes, 1–40 edges).
The underlying document pipeline still preserves original link counts and
required claims. Use the separate v0.2 heading/readability audit on the
**final candidate including its diagram**, then human-review actual GitHub
rendering and substantive truth. A source witness proves existence of a
path in a caller-attested inventory, **not that the diagram relation is
correct**.

This addition is opt-in and preserves the original v0.1 `refine_document`
call signature for consumers not requesting diagrams. The Samuel pin in a
consumer is **not updated automatically** by this PR.

## Gates and authority

1. **Source scope:** no floating refs or assumed completeness; source paths and
   target must stay inside the repository.
2. **Meaning:** original required claims and consumer-owned definitions cannot
   be rewritten by a style preset. The runtime enforces literal preservation
   of declared claims, but **human/consumer review** remains required for
   semantic equivalence and correct source interpretation.
3. **Links:** baseline link targets and their counts must survive; relative
   targets must appear in the attested source inventory (directory links
   resolve to an inventory prefix); non-HTTPS external schemes are rejected.
4. **Renderer:** no custom CSS or JavaScript; fastapi-astro uses a centered
   heading, compact tables and separators. No third-party image dependency.
5. **Delivery:** use Samuel `GITHUB_FILE_CREATE` /
   `GITHUB_FILE_UPDATE` via `repository-mutation` and `GITHUB_PR_CREATE`
   via `pull-request-create`. Re-read exact branch/blob preconditions and
   verify remote post-state. No auto-merge.
6. **CI:** exact-HEAD tests/checks and review remain separate. Successful
   structural validation does not imply a quality PASS.

For modifications after feedback, reuse validated immutable evidence only when
the snapshot and scope are unchanged; always refresh mutable GitHub heads
before writes. This trigger is **not** part of `INIT` and does not change
existing consumer pins.
