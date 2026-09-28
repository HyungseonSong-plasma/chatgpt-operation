from __future__ import annotations

from chatgpt_operation.workflow_failure_ingestion import WorkflowFailureIngestor


def _event(retry_attempt: int = 1) -> dict[str, object]:
    return {
        "consumer": "simulation-ontology",
        "repository": "org/simulation-ontology",
        "workflow": "ci",
        "run_id": "run-duplicate-retry",
        "job": "tests",
        "step": "pytest",
        "head_sha": "abc123",
        "event_type": "workflow_run",
        "occurred_at": "2026-09-28T17:00:00Z",
        "conclusion": "failure",
        "retry_attempt": retry_attempt,
        "failure_signature": "dependency-502",
        "dependency_status": "external",
    }


def test_duplicate_delivery_is_idempotent_and_retries_are_distinct() -> None:
    ingestor = WorkflowFailureIngestor()

    first = ingestor.ingest(_event())
    duplicate = ingestor.ingest(dict(_event()))
    retry = ingestor.ingest(_event(retry_attempt=2))

    assert duplicate == first
    assert retry.stable_identity != first.stable_identity
    assert retry.run_id == first.run_id
    assert len(ingestor.raw_observations()) == 2
