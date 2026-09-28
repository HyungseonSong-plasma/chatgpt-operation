from __future__ import annotations

from chatgpt_operation.workflow_failure_ingestion import (
    CURRENT_CONSUMERS,
    WorkflowFailureIngestor,
)


def _event(consumer: str, retry_attempt: int = 1) -> dict[str, object]:
    return {
        "consumer": consumer,
        "repository": f"org/{consumer}",
        "workflow": "ci",
        "run_id": "run-1",
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


def test_ingestion_accepts_all_current_consumers() -> None:
    ingestor = WorkflowFailureIngestor()

    for consumer in CURRENT_CONSUMERS:
        observation = ingestor.ingest(_event(consumer))
        assert observation.consumer == consumer
        assert observation.failure_category == "EXTERNAL_DEPENDENCY_FAILURE"

    assert len(ingestor.raw_observations()) == len(CURRENT_CONSUMERS)


def test_duplicate_delivery_is_idempotent_but_retry_is_distinct() -> None:
    ingestor = WorkflowFailureIngestor()
    event = _event("simulation-ontology")

    first = ingestor.ingest(event)
    duplicate = ingestor.ingest(dict(event))
    retry = ingestor.ingest(_event("simulation-ontology", retry_attempt=2))

    assert duplicate == first
    assert retry.stable_identity != first.stable_identity
    assert len(ingestor.raw_observations()) == 2


def test_ambiguous_failure_remains_unknown() -> None:
    ingestor = WorkflowFailureIngestor()
    event = _event("moose-test-repo")
    event.pop("dependency_status")
    event.pop("failure_signature")

    assert ingestor.ingest(event).failure_category == "UNKNOWN"
