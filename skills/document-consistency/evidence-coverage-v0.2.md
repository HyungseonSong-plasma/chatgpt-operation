# Evidence coverage v0.2 — experimental, read-only internal API

This document is **not** a public schema/API adoption or an authority transfer.
The display-only v0.1 contract and badge layout remain unchanged.

## Versioned per-axis evidence-coverage contract

`chatgpt_operation.documentation.evidence_audit_v02.audit_evidence_v02`
accepts consumer-owned `declared` status values for decision, implementation and
review, plus the following explicit **v0.2** inputs:

- `snapshot_sha`: exact lowercase 40-character SHA of the **current** consumer
  source snapshot being checked.
- `consumer_repository`: exact `owner/repo` identifier for the consumer; all
  positive-claim witnesses **must** declare this same repository.
- `scope`: one bounded nonempty claim identifier; all positive-claim witnesses
  **must** declare the identical scope. One call must not combine unrelated
  architecture or feature claims.
- `at_revisions`: a complete three-axis map of exact lowercase SHAs.
  `decision` may identify a historical, at-revision ADR; `implementation`
  and `review` must **equal** `snapshot_sha` in this version. This prevents
  a caller from relabeling stale implementation/review evidence as current.
- `witnesses`: per-axis kind, repository, path, revision, scope, provenance,
  and, for a review, an additional reviewer identity distinct from provenance
  (case-insensitive after trimming).
- `independently_verified`: caller-supplied Boolean attestations for each
  axis. These flags are **not** authenticated proof of independent verification.

The audit checks kind, shape, exact revision, repository binding, scope binding,
and caller attestation for **positive** declared statuses. For `decision`, the
witness revision must equal `at_revisions.decision`, not necessarily the current
`snapshot_sha`. The implementation and review evidence revisions must match
their current at-revisions. All mismatches remain `NOT_EVALUATED` and enter
`revalidation_queue`; they do **not** silently demote an adopted historical
decision or elevate an implementation status.

### Example: valid historical decision, current implementation and review

```python
from chatgpt_operation.documentation.evidence_audit_v02 import audit_evidence_v02

report = audit_evidence_v02(
    declared={
        "decision": "ADOPTED",
        "implementation": "IMPLEMENTED",
        "review": "REVIEWED",
    },
    snapshot_sha=current_consumer_commit_sha,
    consumer_repository="owner/consumer",
    scope="bounded-feature-A",
    at_revisions={
        "decision": historical_adr_commit_sha,
        "implementation": current_consumer_commit_sha,
        "review": current_consumer_commit_sha,
    },
    witnesses=verified_witnesses_for_each_axis,
    independently_verified=caller_attestations,
)
```

Expected witness kinds are ADR for decision, SOURCE/TEST for implementation,
and INDEPENDENT_REVIEW for review. Missing, incomplete, wrong-kind, wrong-repo,
wrong-scope, stale, unverifiable or self-reviewed positive claims remain
`NOT_EVALUATED`; nonpositive statuses are never upgraded automatically. An
unsupported literal `UNKNOWN` is rejected by the v0.1 status vocabulary;
`NOT_EVALUATED` represents unknown coverage.

`EVIDENCE_COVERED` means only that positive declarations have correctly shaped,
revision-bound witnesses and **external verification attestations**. It is NOT
semantic `PASS`, a GitHub review, or certification of implemented behavior.
The algorithm makes **no network/GitHub reads** and cannot authenticate a
reviewer, prove the historical ADR commit belongs to the current ancestry,
check actual witness file bytes, confirm rendered Markdown, or establish semantic
compatibility. Those must be independently checked by the consumer's owner and
evidence source, and remain separate acceptance gates.

### Fail-closed regressions and adoption constraints

Unit tests explicitly cover a valid historical ADR beside current implementation,
a wrong-repository witness with a true attestation, a wrong-scope witness,
a changed-source/stale review, attempts to make implementation/review revisions
historical, and a case-variant self-review. Existing missing, malformed, wrong
kind, stale SHA, unverified and unknown-claim tests remain in force.

Conflicting evidence across different scope IDs, external link reachability,
live rendered-page checks and bounded cross-repository verification remain
outside this local deterministic function. Do not change the consumer Samuel
pin, mark semantic acceptance or merge solely because the v0.2 tests pass.
