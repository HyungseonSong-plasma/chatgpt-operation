"""Evidence-preserving workflow-failure ingestion.

The ingestor is append-only and idempotent for duplicate deliveries. Retry
attempts remain distinct observations while sharing the originating run ID.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


CURRENT_CONSUMERS = frozenset(
    {"simulation-ontology", "sol-adapter-moose", "moose-test-repo"}
)


@dataclass(frozen=True)
class WorkflowFailureObservation:
    repository: str
    workflow: str
    run_id: str
    job: str
    step: str | None
    head_sha: str
    event_type: str
    occurred_at: str
    conclusion: str
    retry_attempt: int
    failure_signature: str | None
    failure_category: str
    consumer: str

    @property
    def stable_identity(self) -> tuple[str, ...]:
        return (
            self.repository,
            self.workflow,
            self.run_id,
            self.job,
            self.step or "",
            str(self.retry_attempt),
        )


class WorkflowFailureIngestor:
    """Collect raw workflow failures without lossy deduplication."""

    def __init__(self, consumers: frozenset[str] = CURRENT_CONSUMERS) -> None:
        self._consumers = consumers
        self._observations: dict[tuple[str, ...], WorkflowFailureObservation] = {}

    def ingest(self, raw: Mapping[str, Any]) -> WorkflowFailureObservation:
        consumer = str(raw["consumer"])
        if consumer not in self._consumers:
            raise ValueError(f"unsupported consumer: {consumer}")

        observation = WorkflowFailureObservation(
            repository=str(raw["repository"]),
            workflow=str(raw["workflow"]),
            run_id=str(raw["run_id"]),
            job=str(raw["job"]),
            step=None if raw.get("step") is None else str(raw["step"]),
            head_sha=str(raw["head_sha"]),
            event_type=str(raw["event_type"]),
            occurred_at=str(raw["occurred_at"]),
            conclusion=str(raw["conclusion"]),
            retry_attempt=int(raw["retry_attempt"]),
            failure_signature=(
                None
                if raw.get("failure_signature") is None
                else str(raw["failure_signature"])
            ),
            failure_category=classify_failure(raw),
            consumer=consumer,
        )
        self._observations.setdefault(observation.stable_identity, observation)
        return self._observations[observation.stable_identity]

    def raw_observations(self) -> tuple[WorkflowFailureObservation, ...]:
        return tuple(self._observations.values())


def classify_failure(raw: Mapping[str, Any]) -> str:
    """Classify only when the supplied evidence supports the conclusion."""
    explicit = raw.get("failure_category")
    if explicit:
        return str(explicit)

    dependency_status = str(raw.get("dependency_status", "")).lower()
    if dependency_status in {"external", "upstream", "package_server"}:
        return "EXTERNAL_DEPENDENCY_FAILURE"

    if str(raw.get("workflow_configuration", "")).lower() == "true":
        return "WORKFLOW_CONFIGURATION_FAILURE"
    if str(raw.get("repository_test_failure", "")).lower() == "true":
        return "REPOSITORY_TEST_FAILURE"
    if str(raw.get("central_skill_contract_failure", "")).lower() == "true":
        return "CENTRAL_SKILL_CONTRACT_FAILURE"
    if str(raw.get("transient_infrastructure", "")).lower() == "true":
        return "TRANSIENT_INFRASTRUCTURE_FAILURE"
    return "UNKNOWN"
