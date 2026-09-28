# Weekly workflow-failure ingestion contract

This document defines the evidence contract for weekday workflow-failure collection across the current Paul consumers:

- `simulation-ontology`
- `sol-adapter-moose`
- `moose-test-repo`

## Required raw observation

Each ingested workflow failure must preserve the source event without lossy normalization:

- repository
- workflow
- run ID
- job
- step when available
- head SHA
- event type
- occurrence timestamp
- conclusion
- retry attempt
- stable run identity
- failure signature when deterministically extractable
- failure category when evidence supports classification

Unknown or unavailable fields remain explicit unknown values; they are not inferred from absence.

## Retry and duplicate handling

The stable deduplication identity is derived from the source repository, workflow, run ID, job, step, and retry attempt. Re-ingesting the same observation is idempotent and must not create a second raw record. A later retry attempt remains a distinct observation while retaining the same source run relationship.

Collection must therefore distinguish:

1. an identical delivery retry of the same attempt;
2. a new attempt for the same workflow run;
3. a separate workflow run with a different run ID.

## Failure attribution

Classification is evidence-backed only:

- `REPOSITORY_TEST_FAILURE`
- `CENTRAL_SKILL_CONTRACT_FAILURE`
- `WORKFLOW_CONFIGURATION_FAILURE`
- `EXTERNAL_DEPENDENCY_FAILURE`
- `TRANSIENT_INFRASTRUCTURE_FAILURE`
- `UNKNOWN`

Dependency failures such as an upstream package-server HTTP 502 remain external-dependency evidence and must not be counted as central skill defects. Ambiguous failures remain `UNKNOWN`.

## Consumer-parity validation

A collection validation run must exercise the same ingestion contract for all three current consumers and retain the raw observation identities and resulting deduplication decisions. The validation must confirm that one source event is represented consistently regardless of consumer, while consumer-specific repository and workflow identity remain preserved.

Raw observations are append-only evidence. Derived summaries may be regenerated from a pinned raw snapshot and must retain references to the source observation identities.