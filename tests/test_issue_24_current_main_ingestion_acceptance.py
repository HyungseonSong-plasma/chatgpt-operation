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


def test_current_main_ingests_all_consumers_and_preserves_retry_semantics() -> None:
    ingestor = WorkflowFailureIngestor()

    observations = [ingestor.ingest(_event(consumer)) for consumer in CURRENT_CONSUMERS]
    assert {item.consumer for item in observations} == set(CURRENT_CONSUMERS)
    assert all(item.failure_category == "EXTERNAL_DEPENDENCY_FAILURE" for item in observations)

    first = ingestor.ingest(_event("simulation-ontology"))
    assert ingestor.ingest(_event("simulation-ontology")) == first
    retry = ingestor.ingest(_event("simulation-ontology", retry_attempt=2))
    assert retry.stable_identity != first.stable_identity

    ambiguous = _event("moose-test-repo")
    ambiguous.pop("dependency_status")
    ambiguous.pop("failure_signature")
    assert ingestor.ingest(ambiguous).failure_category == "UNKNOWN"
