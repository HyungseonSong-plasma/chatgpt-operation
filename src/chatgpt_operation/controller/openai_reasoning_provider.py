"""OpenAI Responses API adapter for Samuel semantic reasoning.

The adapter has no repository credentials and returns only a decoded JSON object.
Execution remains owned by Samuel's deterministic pipeline.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request, error

from .reasoning_provider import (
    ProviderFailureKind, ProviderRequestFailure, ProviderUnavailable,
)


DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass
class OpenAIReasoningProvider:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: int = 60
    opener: Callable[..., Any] = request.urlopen
    name: str = "openai"

    @classmethod
    def from_env(cls) -> "OpenAIReasoningProvider":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ProviderUnavailable("OPENAI_API_KEY is not configured")
        return cls(
            api_key=key,
            model=os.environ.get("SAMUEL_OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            base_url=os.environ.get("SAMUEL_OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        )

    def reason(
        self, *, task: str, context: dict[str, Any], attempt: int,
        validation_error: str | None,
    ) -> dict[str, Any]:
        prompt = {
            "task": task,
            "attempt": attempt,
            "validation_error": validation_error,
            "reasoning_context": context,
            "contract": {
                "output": "one JSON object only",
                "allowed_fields": [
                    "operation", "decision_id",
                    "compatible_with_locked_decisions",
                    "revision_requested", "action_plan",
                ],
                "no_execution": True,
            },
        }
        body = json.dumps({
            "model": self.model,
            "input": json.dumps(prompt, sort_keys=True, separators=(",", ":")),
        }).encode()
        req = request.Request(
            self.base_url + "/responses",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener(req, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode())
        except error.HTTPError as exc:
            raise self._http_failure(exc) from exc
        except (error.URLError, TimeoutError) as exc:
            raise ProviderRequestFailure(
                "OpenAI reasoning provider network request failed",
                kind=ProviderFailureKind.NETWORK,
                retryable=True,
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderRequestFailure(
                "OpenAI reasoning provider returned invalid response JSON",
                kind=ProviderFailureKind.UNKNOWN,
                retryable=False,
            ) from exc
        text = self._output_text(payload)
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable("OpenAI reasoning provider returned non-JSON text") from exc
        if not isinstance(decoded, dict):
            raise ProviderUnavailable("OpenAI reasoning provider returned non-object JSON")
        return decoded

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        parts: list[str] = []
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    parts.append(content["text"])
        if not parts:
            raise ProviderUnavailable("OpenAI response contained no text output")
        return "".join(parts).strip()


    @staticmethod
    def _http_failure(exc: error.HTTPError) -> ProviderRequestFailure:
        code = None
        error_type = None
        try:
            raw = exc.read().decode()
            payload = json.loads(raw)
            detail = payload.get("error", {}) if isinstance(payload, dict) else {}
            if isinstance(detail, dict):
                value = detail.get("code")
                code = value if isinstance(value, str) else None
                value = detail.get("type")
                error_type = value if isinstance(value, str) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        token = (code or error_type or "").lower()
        quota_tokens = ("quota", "billing", "credit", "spend")
        if exc.code == 429 and any(x in token for x in quota_tokens):
            kind, retryable = ProviderFailureKind.QUOTA_OR_BILLING, False
        elif exc.code == 429:
            kind, retryable = ProviderFailureKind.RATE_LIMITED, True
        elif exc.code in (401, 403):
            kind, retryable = ProviderFailureKind.AUTHENTICATION, False
        elif 400 <= exc.code < 500:
            kind, retryable = ProviderFailureKind.BAD_REQUEST, False
        elif exc.code >= 500:
            kind, retryable = ProviderFailureKind.SERVER_ERROR, True
        else:
            kind, retryable = ProviderFailureKind.UNKNOWN, False
        return ProviderRequestFailure(
            "OpenAI reasoning provider HTTP request failed",
            kind=kind,
            status=exc.code,
            provider_code=code or error_type,
            retryable=retryable,
        )
