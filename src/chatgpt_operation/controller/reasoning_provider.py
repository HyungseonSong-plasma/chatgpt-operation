"""Provider-neutral semantic reasoning runtime contract."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol

from .reasoning import RawReasoningRunner, ReasoningNodeError


class SemanticReasoningProvider(Protocol):
    name: str
    def reason(
        self,
        *,
        task: str,
        context: dict[str, Any],
        attempt: int,
        validation_error: str | None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProviderStatus:
    available: bool
    provider: str | None
    reason: str


class ProviderUnavailable(ReasoningNodeError):
    pass


@dataclass
class ReasoningProviderRegistry:
    provider: SemanticReasoningProvider | None = None

    def status(self) -> ProviderStatus:
        if self.provider is None:
            return ProviderStatus(False,None,"no semantic reasoning provider configured")
        return ProviderStatus(True,self.provider.name,"semantic reasoning provider configured")

    def runner(self) -> RawReasoningRunner:
        if self.provider is None:
            raise ProviderUnavailable("no semantic reasoning provider configured")
        provider=self.provider
        def run(task:str,context:dict[str,Any],attempt:int,validation_error:str|None)->dict[str,Any]:
            raw=provider.reason(
                task=task,context=context,attempt=attempt,validation_error=validation_error
            )
            if not isinstance(raw,dict):
                raise ProviderUnavailable("semantic reasoning provider returned non-object")
            return raw
        return run
