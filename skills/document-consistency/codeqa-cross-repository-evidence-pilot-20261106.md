# codeQA cross-repository evidence pilot — 2026-11-06

**Disposition: BOUNDED_SOURCE_PROVENANCE_CONFIRMED / SEMANTIC_REVIEW_REQUIRED.**

This is a manually bounded, read-only **GitHub connector observation** for Samuel's
experimental evidence-coverage v0.2. It is NOT an independently approved
architecture review, a current source-wide implementation certificate or a
GitHub-rendered-page test. Treat every observed ref and blob as pinned to the
commit below. No file was modified in the consumer repository.

## Inputs and trust boundary

- Consumer: `HyungseonSong-plasma/codeQA`, [documentation PR #289](https://github.com/HyungseonSong-plasma/codeQA/pull/289), exact candidate HEAD `24040c02ea97056de89c6711e847b4f727fb0dcb` (still unmerged when inspected).
- Consumer baseline: `main@23c2166bd3b2b0c825b207e856b95c68e0e24070`.
- Architecture guide's **source reference**: `21cea5bf0841f2049889877a340a1887bd7d8582`.
- Document creation: [PR #34](https://github.com/HyungseonSong-plasma/codeQA/pull/34), branch head `e0b84e97d1bf18ba48f115026217c8bf1fadfbb4`, base `21cea5bf0841f2049889877a340a1887bd7d8582`, merge commit `519b32f8b0c883f1689f07ba1ddaa559cd897064`.
- All comparisons and file reads were executed through a GitHub repository connector. Local unit tests cannot independently authenticate GitHub's contents, reviewers, actual execution, or external deep links.

## Pinned observations

| Subject | Exact observation | Evidence and limitation |
| --- | --- | --- |
| Reference SHA ancestry | Comparing `21cea5bf...` against codeQA `main@23c2166b...` and PR #289 HEAD returned `ahead` with merge-base equal to `21cea5bf...`; it is an ancestor of both. | [Source commit](https://github.com/HyungseonSong-plasma/codeQA/commit/21cea5bf0841f2049889877a340a1887bd7d8582) |
| Documentation origin | `docs/architecture.md` and `docs/adr/0001-contract-authority-and-versioning.md` are **absent** at `21cea5bf...`; both are introduced by PR #34, subsequently merged. Comparing the PR #34 **merge commit** to PR #289 HEAD returned `ahead`, merge-base exactly `519b32f8...`. | [PR #34](https://github.com/HyungseonSong-plasma/codeQA/pull/34), [merge commit](https://github.com/HyungseonSong-plasma/codeQA/commit/519b32f8b0c883f1689f07ba1ddaa559cd897064) |
| Architecture source | `src/codeqa/pipeline/python.py` fetched at `21cea5bf...`, at the PR #34 merge and at PR #289 HEAD has the identical reported Git blob SHA `af599495d06e8d48d4e2bd014d71dfd9fcd2d6ec`. | [Pinned source](https://github.com/HyungseonSong-plasma/codeQA/blob/21cea5bf0841f2049889877a340a1887bd7d8582/src/codeqa/pipeline/python.py). This checks one source file's exact content identity, not runtime semantics. |
| Accepted scoped ADR | `docs/adr/0001-contract-authority-and-versioning.md` exists at the PR #34 merge and PR #289 HEAD with identical reported Git blob SHA `cb0729e8f210ec9f58dd83c6cc32f67720acb03a`. The text says `Status: Accepted, 2026-10-23`, decision scope: canonical contract authority/versioning. | [Pinned ADR](https://github.com/HyungseonSong-plasma/codeQA/blob/519b32f8b0c883f1689f07ba1ddaa559cd897064/docs/adr/0001-contract-authority-and-versioning.md). **Its acceptance applies to its bounded CCG/contract scope; it does not cover all architecture-guide assertions.** |
| Contract bytes | `contracts/ccg/graph-v0.1.schema.json` fetched at the PR #34 merge and PR #289 HEAD has identical reported blob SHA `75a0116a87d7eb3929ac148b4d142c4764f53c87` with `$id=urn:codeqa:ccg:graph:v0.1`. | [Pinned schema](https://github.com/HyungseonSong-plasma/codeQA/blob/24040c02ea97056de89c6711e847b4f727fb0dcb/contracts/ccg/graph-v0.1.schema.json). Byte identity is not a full validator behavior proof. |
| Updated guide | `docs/architecture.md` originated with blob `aba1e5eaaafea8cab97f72ee53a3b66ebb420340` at PR #34 head and is blob `4af214abe134f5da4af5638db822adca98c3a9ba` at PR #289 HEAD. The latter explicitly says **ADOPTED at source revision**, Implementation/Review `NOT_EVALUATED`. | [Pinned candidate guide](https://github.com/HyungseonSong-plasma/codeQA/blob/24040c02ea97056de89c6711e847b4f727fb0dcb/docs/architecture.md) |
| Consumer claim catalog | `docs/documentation-catalog-v0.1.json` blob `8406a97c9a6da0ec99343e73c912928b576803ce`: architecture guide has role `ADOPTED_ARCHITECTURE_GUIDE` but `authority_review=NOT_EVALUATED`; documentation-governance proposal is `PROPOSED`/`REVIEW_REQUIRED`. | [Pinned catalog](https://github.com/HyungseonSong-plasma/codeQA/blob/24040c02ea97056de89c6711e847b4f727fb0dcb/docs/documentation-catalog-v0.1.json) |
| Render source, not browser | `decision-adopted.svg` fetched at PR #289 HEAD has reported blob `55e219df2917219e158ff2dfd1914d574e44cf4c`, `height=22`, `rx=11`, alt/ARIA description in source. | [Pinned SVG](https://github.com/HyungseonSong-plasma/codeQA/blob/24040c02ea97056de89c6711e847b4f727fb0dcb/docs/assets/document-status/decision-adopted.svg). Browser rendering, mobile clipping and screen-reader output NOT_EVALUATED. |
| Independent review | PR #34: **0 submitted reviews**; PR #289: two submitted **COMMENTED** reviews by repository owner `HyungseonSong-plasma`, not an independent approval; Samuel PR #252: **0 submitted reviews**. | [PR #34](https://github.com/HyungseonSong-plasma/codeQA/pull/34), [PR #289](https://github.com/HyungseonSong-plasma/codeQA/pull/289), [Samuel #252](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/252) |
| Consumer Samuel pin | `docs/operating_system/central_skills.json` has identical reported blob `bc33292e648e7ae74aae38cc21a9080c8119b3c8` at codeQA baseline and PR #289. The Samuel revision remains `c803cd6b77c6d112df33d8679bac32f993a658b0`. | [Pinned consumer manifest](https://github.com/HyungseonSong-plasma/codeQA/blob/24040c02ea97056de89c6711e847b4f727fb0dcb/docs/operating_system/central_skills.json). Experimental Samuel PR #252 is **not** adopted. |

## Contract alignment and outcome

A historical **source snapshot** `21cea5bf...` must **not** be used as the
revision of an ADR that did not yet exist. For a narrowly declared decision
about canonical CCG contract authority/versioning, the existing
`docs/adr/0001-contract-authority-and-versioning.md` can instead be read at
the actual PR #34 **merge** revision `519b32f8...`, while implementation
evidence can be read at the current PR #289 HEAD. These are separate axes.
The scope of this ADR does **not** automatically cover the complete architecture
guide. In Samuel `audit_evidence_v02`, matching revisions, repository and
scope establish only shaped **evidence coverage** when caller-attested.

**Verified in this bounded exercise:** referenced Git commit availability and
ancestry, GitHub-reported file blob identity for selected exact revisions,
origin of the documentation and ADR, visible declared label/catalog statuses,
repository attribution, and recorded PR review states.

**Not verified:** end-to-end semantic equivalence, complete ownership of all
architecture claims, GitHub rendered pages and anchors, external backlinks,
actual reviewer identity beyond the GitHub account display, independent
approval, or any claims of contemporaneous acceptance of an ADR at
`21cea5bf...`. No claim of `EVIDENCE_COVERED` for the entire guide, no
`REVIEWED` label promotion, no downstream pin update, no merge.

**Next gate:** an independent domain owner must select a narrow claim scope,
inspect actual source/tests/contracts at the exact revision, decide whether
the ADR is normatively sufficient for that scope, and inspect GitHub-rendered
pages. Absent those checks, retain `REVIEW_REQUIRED`.
