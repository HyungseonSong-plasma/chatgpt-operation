"""Typed reasoning-node boundary with bounded validation repair."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from .research import AnalysisResult, HypothesisResult, ResearchStateError


class ReasoningNodeError(RuntimeError):
    """Raised when a reasoning node cannot produce a valid typed result."""


T = TypeVar("T")
RawReasoningRunner = Callable[
    [str, dict[str, Any], int, str | None],
    dict[str, Any],
]
Parser = Callable[[dict[str, Any]], T]


@dataclass(frozen=True)
class ReasoningRequest:
    task: str
    context: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task.strip():
            raise ReasoningNodeError("task must be a non-empty string")
        if not isinstance(self.context, dict):
            raise ReasoningNodeError("context must be an object")


@dataclass(frozen=True)
class StructuredReasoningNode(Generic[T]):
    parser: Parser[T]
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ReasoningNodeError("max_attempts must be >= 1")

    def run(
        self,
        request: ReasoningRequest,
        runner: RawReasoningRunner,
    ) -> T:
        validation_error: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            raw = runner(
                request.task,
                dict(request.context),
                attempt,
                validation_error,
            )
            if not isinstance(raw, dict):
                validation_error = "reasoning runner must return an object"
                continue
            try:
                return self.parser(raw)
            except (ResearchStateError, TypeError, ValueError) as exc:
                validation_error = str(exc)

        raise ReasoningNodeError(
            f"{request.task} failed typed validation after "
            f"{self.max_attempts} attempts: {validation_error}"
        )


def hypothesis_node(*, max_attempts: int = 2) -> StructuredReasoningNode[HypothesisResult]:
    return StructuredReasoningNode(
        parser=HypothesisResult.from_dict,
        max_attempts=max_attempts,
    )


def analysis_node(*, max_attempts: int = 2) -> StructuredReasoningNode[AnalysisResult]:
    return StructuredReasoningNode(
        parser=AnalysisResult.from_dict,
        max_attempts=max_attempts,
    )
