# DEA v0.2 verification receipt — 2026-11-06

**Scope:** Read-only live GitHub readback plus exact-head CI validation.
**Repository:** HyungseonSong-plasma/chatgpt-operation
**Draft PR:** #249 (OPEN, unmerged, no independent reviews)
**Verified source HEAD:** `203f945d02c1579dcce4625c1a1445a1e159c236`
**Exact-head CI:** [Run 42211124324](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42211124324), `pull_request`, `completed/success`.

## Observed results

| Claim | Live evidence | Verdict |
| --- | --- | --- |
| CI test suite at exact HEAD | Job 127869725177, completed/success; logs: **745 Python unit tests passed**, including DEA attestation identity, signature-CLI argument, synthetic signed payload, malformed ZIP and human-review packet tests | **PASS — bounded implementation tests** |
| Real codeQA immutable preview | GitHub CI test `test_preview_pr289_head_without_mutating_codeqa` passed | **PASS — pinned read-only source preview, not domain-wide equivalence** |
| Actual Artifact for CI Run 42211124324 | GitHub Actions REST artifact-list readback: `total_count=0`, no listed artifacts | **MISSING_EVIDENCE — HUMAN_REVIEW_REQUIRED** |
| Actual signed DEA evidence payload | No `dea-evidence.zip` was uploaded to that run | **NOT_EVALUATED** |
| Actual Sigstore/SLSA verification | No uploaded DEA subject/attestation available to verify | **NOT_EVALUATED** |
| Independent producing Job and run-to-artifact attestation | Existing `.github/workflows/ci.yml` performs tests and no DEA producer/attestation step; deployed main-workflow inventory contains no DEA signing producer workflow | **BLOCKED_BY_WORKFLOW_AUTHORITY** |
| DEA branch competition | No candidate A/B/C branches authorized or created through this pilot | **NOT_STARTED** |
| codeQA phase-1 common baseline | codeQA PR #289 OPEN, unmerged; HEAD `24040c02ea97056de89c6711e847b4f727fb0dcb` | **BLOCKED — adopted baseline absent** |

### Human review vs automatic admission

The missing Artifact is a legitimate **human review exception**, not a passed or silently discarded artifact. The verifier must retain the Run ID and SHA, report `HUMAN_REVIEW_REQUIRED` with category `MISSING_EVIDENCE`, and keep Fitness semantic gate `UNKNOWN` and `pareto_eligible=false`. There are **no original DEA bytes to preserve** for this run, so do not claim that a nonexistent ZIP was archived. Delivery of a review packet to a human via GitHub comment/inbox is not configured; this report is the durable record.

A verification failure does not permit executing unsafe ZIP content, treating unknowns as PASS, merging the Draft PR or granting candidate-branch authority.

### Official Workflow adoption finding

Current `main` policy at `automation/samuel/repository-mutation-policy.json` denies `.github/workflows/**` (including via a different provider). This run and verification did not modify this policy, create a signed Artifact or deploy/dispatch a new workflow. The user's authorization to **verify** does not by itself repeal this policy.

The approved adoption review must pin the signing workflow/action revisions, grant only necessary scoped GitHub permissions (review `contents:read`, `id-token:write`, `attestations:write`, and `artifact-metadata:write` when using the storage-record integration), provide separate trusted producer/validator job provenance, and correlate attestation subject SHA-256 and signer/source/run identities with the GitHub-uploaded Artifact. The v2 payload correctly separates pre-upload signed subject from post-upload Artifact ID.

### Decision / next gate

**VERIFICATION_BOUNDED_PASS, LIVE_ATTESTATION_BLOCKED, HUMAN_REVIEW_REQUIRED_FOR_MISSING_EVIDENCE.**  
Do **not** claim end-to-end cryptographic producer verification. Obtain workflow-policy authority via the normal governed route and adopt a protected producer before a fresh live signed Artifact run. After signed Artifact upload, re-fetch its exact Run/Artifact identities and independently invoke real `gh attestation verify`; only then continue semantic/fitness verification.

References: [DEA contract](dea-v02-evaluation-contract.md), [producer adoption contract](dea-v02-producer-attestation-adoption.md), [Artifact provenance](dea-v02-artifact-provenance.md).

Official verification contracts:
- https://cli.github.com/manual/gh_attestation_verify
- https://github.com/actions/attest
