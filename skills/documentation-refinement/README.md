# documentation-refinement

**OS:** Samuel · **Activation:** `DOCUMENTATION_REFINEMENT` (on demand)  
**Machine contract:** [contract.json](contract.json)  
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
  -> DESIGN: render minimal or fastapi-astro Markdown
  -> VALIDATE: enforce links, claims, evidence and safe paths
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
    baseline_markdown="[Capability](adapters/capability-v0.1.schema.json)",
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
