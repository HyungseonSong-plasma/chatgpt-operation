"""Deterministic lifecycle harness for end-to-end controller fault injection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .action_plan import ExecutorKind
from .execution import ExecutionResult, ExecutionStatus, transition_from_execution
from .invariants import Continuation, ContinuationKind, require_single_continuation
from .research import ResearchStage, ResearchState


class LifecycleWriteError(RuntimeError):
    pass


@dataclass
class LifecycleEvidence:
    hypothesis: str | None = None
    experiment: str | None = None
    test_result: str | None = None
    final_write: str | None = None
    events: list[str] = field(default_factory=list)


@dataclass
class LifecycleScenario:
    state: ResearchState
    evidence: LifecycleEvidence = field(default_factory=LifecycleEvidence)

    def establish_hypothesis(self, value: str) -> None:
        self.evidence.hypothesis = value
        self.evidence.events.append("hypothesis")
        self.state.stage = ResearchStage.GENERATE_HYPOTHESIS
        self.state.revision += 1

    def design_experiment(self, value: str) -> None:
        if not self.evidence.hypothesis:
            raise LifecycleWriteError("experiment requires hypothesis")
        self.evidence.experiment = value
        self.evidence.events.append("experiment")
        self.state.stage = ResearchStage.DESIGN_EXPERIMENT
        self.state.revision += 1

    def record_test(self, value: str) -> None:
        if not self.evidence.experiment:
            raise LifecycleWriteError("test requires experiment")
        self.evidence.test_result = value
        self.evidence.events.append("test")
        self.state.stage = ResearchStage.ANALYZE
        self.state.revision += 1

    def finalize(self, writer: Callable[[str], None]) -> Continuation:
        if not self.evidence.test_result:
            raise LifecycleWriteError("finalization requires verified test evidence")
        self.state.stage = ResearchStage.DECIDE
        self.state.revision += 1
        try:
            writer(self.evidence.test_result)
        except (OSError, LifecycleWriteError) as exc:
            self.evidence.events.append("final_write_blocked")
            import hashlib
            action_id = hashlib.sha256(
                f"{self.state.research_id}:final_write".encode("utf-8")
            ).hexdigest()
            execution = ExecutionResult(
                research_id=self.state.research_id,
                action_id=action_id,
                executor=ExecutorKind.REPOSITORY_MUTATION,
                status=ExecutionStatus.FAILED,
                observation=f"final write blocked: {type(exc).__name__}: {exc}",
                retryable=True,
                details={
                    "attempted": True,
                    "error_type": type(exc).__name__,
                    "provider": "repository_mutation",
                },
            )
            continuation = Continuation(
                ContinuationKind.RETRY,
                execution.observation,
                execution,
            )
            return require_single_continuation(self.state, (continuation,))
        self.evidence.final_write = self.evidence.test_result
        self.evidence.events.append("final_write")
        # Successful final write becomes typed executor evidence. Completion is
        # authorized by that evidence, never by lifecycle prose.
        import hashlib
        action_id = hashlib.sha256(
            f"{self.state.research_id}:final_write".encode("utf-8")
        ).hexdigest()
        execution = ExecutionResult(
            research_id=self.state.research_id,
            action_id=action_id,
            executor=ExecutorKind.REPOSITORY_MUTATION,
            status=ExecutionStatus.PASS,
            observation="final write committed",
            details={"evidence": "writer returned successfully"},
        )
        transition_from_execution(
            self.state,
            execution,
            ResearchStage.COMPLETE,
        )
        return Continuation(ContinuationKind.COMPLETE, "lifecycle completed")

    def resume_finalization(self, writer: Callable[[str], None]) -> Continuation:
        """Retry only the blocked final write; prior scientific work must be reused."""
        if self.evidence.final_write is not None:
            return Continuation(ContinuationKind.COMPLETE, "final write already committed")
        return self.finalize(writer)
