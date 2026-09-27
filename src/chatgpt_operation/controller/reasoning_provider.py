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


class ProviderFailureKind:
    RATE_LIMITED = "rate_limited"
    QUOTA_OR_BILLING = "quota_or_billing"
    AUTHENTICATION = "authentication"
    BAD_REQUEST = "bad_request"
    SERVER_ERROR = "server_error"
    NETWORK = "network"
    UNKNOWN = "unknown"


class ProviderRequestFailure(ProviderUnavailable):
    def __init__(
        self, message: str, *, kind: str, status: int | None = None,
        provider_code: str | None = None, retryable: bool = False,
    ):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.provider_code = provider_code
        self.retryable = retryable


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
