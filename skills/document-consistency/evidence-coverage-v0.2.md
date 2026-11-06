# Evidence coverage v0.2 — experimental, read-only internal API

This document is **not** a public schema/API adoption or an authority transfer.
The display-only v0.1 contract and badge layout remain unchanged.

`chatgpt_operation.documentation.evidence_audit_v02.audit_evidence_v02`
accepts a consumer-owned `declared` map (decision, implementation, review),
an exact source snapshot SHA, per-axis `witnesses`, and caller-attested
`independently_verified` booleans. It performs **no GitHub reads** and cannot
authenticate a reviewer. Witnesses carry kind, repository, path, revision
(exact SHA), scope, provenance; a review additionally carries reviewer distinct
from provenance. It checks coverage only, not semantic correctness.

Accepted kinds: decision ADR, implementation SOURCE/TEST, review
INDEPENDENT_REVIEW. Missing, incomplete, wrong-kind, stale, unverifiable
or self-reviewed positive claims remain `NOT_EVALUATED` in the verified
projection and enter the revalidation queue. Nonpositive statuses never become
positive automatically. An unsupported literal `UNKNOWN` is rejected by
v0.1's status vocabulary; `NOT_EVALUATED` represents unknown coverage.
`EVIDENCE_COVERED` means only all positive declarations have correctly shaped
exact-revision evidence with an external verification **attestation**. It does
not mean `PASS`, independent GitHub verification, implementation behavior,
or a human-approved architecture decision.

**Important limitation:** v0.2 currently compares each witness revision to
one snapshot SHA. This conservative rule can flag historical at-revision ADRs
as stale even when they are valid. It is **not** an automatic authority
demotion; consumer reviewers must supply a revision/scope mapping before
a broader public contract. Conflict detection between independent competing
claims and bounded cross-repository verification are still outstanding.

Adversarial regression tests cover stale SHA, wrong evidence kind, missing
provenance, missing witness, false verification, self-review and unknown claims.
Do not change the consumer Samuel pin or merge this PR until independent
review and real rendered-page checks are complete.
