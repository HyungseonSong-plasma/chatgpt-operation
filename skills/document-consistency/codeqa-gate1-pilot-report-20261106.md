# codeQA Gate 1 pinned source pilot — 2026-11-06

**Scope:** exact codeQA PR #289 snapshot, CCG v0.1 contract identity and one
static Core-module import boundary. **Machine check result:**
`SCOPED_CHECKS_PASS`. **Independent review:** `REVIEW_REQUIRED`.

## Source acquisition and immutable identity

Consumer: `HyungseonSong-plasma/codeQA`, exact PR #289 HEAD
`24040c02ea97056de89c6711e847b4f727fb0dcb`.

GitHub connector retrieval at that SHA provided these exact raw files and
reported Git blob SHAs. The copies committed to Samuel's **Draft PR #252**
were read back through GitHub and independently compared to the original
reported blob SHA.

| CodeQA path | Reported Git blob SHA | Static predicate and meaning |
| --- | --- | --- |
| `contracts/ccg/graph-v0.1.schema.json` | `75a0116a87d7eb3929ac148b4d142c4764f53c87` | `JSON_POINTER_EQUALS` at `/$id` for `urn:codeqa:ccg:graph:v0.1` |
| `src/codeqa/core/graph.py` | `0545d0266b9e9856f1be6ec875c46e23b7588655` | `PYTHON_IMPORT_ABSENT` for `codeqa.adapters` within **this one Python file** |

The exact inputs are stored below
`tests/fixtures/document_consistency/codeqa_pr289/`. The pinned declaration
is [codeqa-gate1-pilot-v0.1.json](codeqa-gate1-pilot-v0.1.json).

## Reproduction

The read-only, reusable runner
`chatgpt_operation.documentation.gate1_manifest_v01` consumes a
caller-supplied local repository snapshot containing the manifest paths,
recomputes each expected Git blob SHA from UTF-8 bytes and evaluates every
explicitly required check. It neither retrieves a GitHub PR nor mutates files.

From the root of Samuel's checkout:

```sh
PYTHONPATH=src python -m chatgpt_operation.documentation.gate1_manifest_v01 \
  --manifest skills/document-consistency/codeqa-gate1-pilot-v0.1.json \
  --snapshot-root tests/fixtures/document_consistency/codeqa_pr289
```

Reusing this manifest against a future codeQA HEAD is **not** valid; obtain a
new exact PR source SHA, approve a refreshed manifest and re-acquire its files.
A false GitHub source identity, an invented manifest, or a replaced SHA is
not authenticated by a local read-only function alone. The pinned copies were
cross-checked through the connector at the stated head, **not** refreshed
against every subsequent codeQA commit.

## Scoped outcomes

- `ccg_contract_id = PASS`: the pinned schema's `$id` matches the
  expected CCG v0.1 identity. This is not a JSON Schema/CCG validation proof.
- `core_no_adapters_import = PASS`: `core/graph.py` parses as Python and
  has no absolute `codeqa.adapters` import. The checker does not prove the
  absence of imports in other files, dynamic imports, transitive runtime
  dependencies, or a full architectural boundary.
- `Gate 1 = SCOPED_CHECKS_PASS`: exactly the above properties passed.
- `Gate 2 = REVIEW_REQUIRED`; `semantic_certification = NOT_EVALUATED`.

CI for [source and test commit](https://github.com/HyungseonSong-plasma/chatgpt-operation/commit/98018ace9d1ab7029de81e54095acd41d281b21a)
[run 42251387737](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42251387737):
**876 tests OK**, including eight negative/positive codeQA pinned pilot tests.
Malformed/missing sources, altered blobs, wrong identity, synthetic prohibited
imports, extra source files and an attempted approval injection are rejected
by the tests.

## Gate 2 items retained for human decision

1. Whether the ADR 0001 CCG authority claim adequately specifies its
   normative scope and aligns with the actual validator behavior and
   architecture model (not inferable from a schema ID alone).
2. Whether the declared Core/Adapter dependency separation holds across the
   **entire** relevant package and its runtime behavior, beyond the one
   pilot source file. This should be automatically expanded before a reviewer
   is asked to evaluate general architecture.
3. Whether the original PR #34 decision and codeQA PR #289 changes satisfy
   owner-approved semantic acceptance; prior review records did not show
   a separate independent approval.

**No status promotion:** codeQA `authority_review=NOT_EVALUATED` and the
Review badges remain unchanged; no Samuel consumer pin update; no merge of
either draft or codeQA documentation PR. This is only an additive Gate 1
read-only consumer pilot.
