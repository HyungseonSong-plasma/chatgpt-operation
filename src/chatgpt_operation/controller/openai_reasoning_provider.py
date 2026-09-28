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

SHADOW_ISSUE_REASONING_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": ["analyze", "implement_gap", "propose_revision"]},
        "decision_id": {"type": ["string", "null"]},
        "compatible_with_locked_decisions": {"type": "boolean"},
        "revision_requested": {"type": "boolean"},
        "action_plan": {"type": "null"},
        "blocker": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "capability": {"type": "string"},
                        "alternatives_considered": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "exhausted": {"type": "boolean"},
                    },
                    "required": [
                        "capability",
                        "alternatives_considered",
                        "exhausted",
                    ],
                    "additionalProperties": False,
                },
            ],
        },
    },
    "required": [
        "operation", "decision_id", "compatible_with_locked_decisions",
        "revision_requested", "action_plan", "blocker",
    ],
    "additionalProperties": False,
}

_NON_TERMINAL_STAGES = [
    "define_problem",
    "acquire_knowledge",
    "generate_hypothesis",
    "design_validation",
    "design_experiment",
    "implement",
    "execute",
    "analyze",
    "decide",
]


def _closed_object(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _repository_payload_schemas() -> list[dict[str, Any]]:
    common = {
        "schema_version": {"type": "integer", "enum": [1]},
        "repository": {"type": "string"},
    }
    return [
        _closed_object({
            **common,
            "resource": {"type": "string", "enum": ["branch"]},
            "action": {"type": "string", "enum": ["create"]},
            "target": _closed_object({
                "name": {"type": "string"},
            }),
            "expected": _closed_object({
                "absent": {"type": "boolean", "enum": [True]},
            }),
            "desired": _closed_object({
                "sha": {"type": "string"},
            }),
            "commit_message": {"type": "null"},
        }),
        _closed_object({
            **common,
            "resource": {"type": "string", "enum": ["file"]},
            "action": {"type": "string", "enum": ["create"]},
            "target": _closed_object({
                "path": {"type": "string"},
                "branch": {"type": "string"},
            }),
            "expected": _closed_object({
                "absent": {"type": "boolean", "enum": [True]},
            }),
            "desired": _closed_object({
                "content": {"type": "string"},
            }),
            "commit_message": {"type": "string"},
        }),
        _closed_object({
            **common,
            "resource": {"type": "string", "enum": ["file"]},
            "action": {"type": "string", "enum": ["update"]},
            "target": _closed_object({
                "path": {"type": "string"},
                "branch": {"type": "string"},
            }),
            "expected": _closed_object({
                "sha": {"type": "string"},
            }),
            "desired": _closed_object({
                "content": {"type": "string"},
            }),
            "commit_message": {"type": "string"},
        }),
        _closed_object({
            **common,
            "resource": {"type": "string", "enum": ["file"]},
            "action": {"type": "string", "enum": ["delete"]},
            "target": _closed_object({
                "path": {"type": "string"},
                "branch": {"type": "string"},
            }),
            "expected": _closed_object({
                "sha": {"type": "string"},
            }),
            "desired": _closed_object({}),
            "commit_message": {"type": "string"},
        }),
    ]


def _native_payload_schemas() -> list[dict[str, Any]]:
    common = {
        "repository": {"type": "string"},
    }
    return [
        _closed_object({
            **common,
            "action": {"type": "string", "enum": ["create_pr"]},
            "target": _closed_object({
                "head": {"type": "string"},
                "base": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            }),
            "preconditions": _closed_object({
                "pr_present": {"type": "boolean", "enum": [False]},
            }),
            "desired_postcondition": _closed_object({
                "pr_present": {"type": "boolean", "enum": [True]},
            }),
        }),
        _closed_object({
            **common,
            "action": {"type": "string", "enum": ["close_issue"]},
            "target": _closed_object({
                "number": {"type": "integer"},
            }),
            "preconditions": _closed_object({
                "issue_state": {"type": "string", "enum": ["open"]},
            }),
            "desired_postcondition": _closed_object({
                "issue_state": {"type": "string", "enum": ["closed"]},
            }),
        }),
        _closed_object({
            **common,
            "action": {"type": "string", "enum": ["comment_issue"]},
            "target": _closed_object({
                "number": {"type": "integer"},
                "body": {"type": "string"},
                "marker": {"type": "string"},
            }),
            "preconditions": _closed_object({
                "issue_state": {"type": "string", "enum": ["open"]},
                "comment_present": {"type": "boolean", "enum": [False]},
            }),
            "desired_postcondition": _closed_object({
                "comment_present": {"type": "boolean", "enum": [True]},
            }),
        }),
        _closed_object({
            **common,
            "action": {"type": "string", "enum": ["merge_pr"]},
            "target": _closed_object({
                "number": {"type": "integer"},
                "expected_head_sha": {"type": "string"},
            }),
            "preconditions": _closed_object({}),
            "desired_postcondition": _closed_object({
                "merged": {"type": "boolean", "enum": [True]},
            }),
        }),
        _closed_object({
            **common,
            "action": {"type": "string", "enum": ["dispatch_workflow"]},
            "target": _closed_object({
                "workflow": {"type": "string"},
                "ref": {"type": "string"},
            }),
            "preconditions": _closed_object({
                "dispatched": {"type": "boolean", "enum": [False]},
                "ref": {"type": "string"},
            }),
            "desired_postcondition": _closed_object({
                "dispatched": {"type": "boolean", "enum": [True]},
            }),
        }),
    ]


def _decision_risk_schema() -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "null"},
            _closed_object({
                "impact": {"type": "number"},
                "uncertainty": {"type": "number"},
                "irreversibility": {"type": "number"},
            }),
        ],
    }


def _action_plan_variant(
    executor: str,
    payload_schema: dict[str, Any],
) -> dict[str, Any]:
    return _closed_object({
        "schema_version": {"type": "integer", "enum": [1]},
        "research_id": {"type": "string"},
        "stage": {"type": "string", "enum": _NON_TERMINAL_STAGES},
        "executor": {"type": "string", "enum": [executor]},
        "payload": payload_schema,
        "expected_observation": {"type": "string"},
        "decision_risk": _decision_risk_schema(),
    })


ACTION_PLAN_SCHEMA = {
    "anyOf": [
        {"type": "null"},
        *[
            _action_plan_variant("repository_mutation", payload)
            for payload in _repository_payload_schemas()
        ],
        *[
            _action_plan_variant("github_native", payload)
            for payload in _native_payload_schemas()
        ],
    ],
}


PRODUCTION_ISSUE_REASONING_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["analyze", "implement_gap", "propose_revision"],
        },
        "decision_id": {"type": ["string", "null"]},
        "compatible_with_locked_decisions": {"type": "boolean"},
        "revision_requested": {"type": "boolean"},
        "action_plan": ACTION_PLAN_SCHEMA,
        "blocker": {
            "anyOf": [
                {"type": "null"},
                _closed_object({
                    "capability": {"type": "string"},
                    "alternatives_considered": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "exhausted": {"type": "boolean"},
                }),
            ],
        },
    },
    "required": [
        "operation",
        "decision_id",
        "compatible_with_locked_decisions",
        "revision_requested",
        "action_plan",
        "blocker",
    ],
    "additionalProperties": False,
}


# Backward-compatible name for non-executing qualification callers.
ISSUE_REASONING_SCHEMA = SHADOW_ISSUE_REASONING_SCHEMA


@dataclass
class OpenAIReasoningProvider:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: int = 60
    opener: Callable[..., Any] = request.urlopen
    allow_action_plan: bool = False
    name: str = "openai"

    @classmethod
    def from_env(
        cls, *, allow_action_plan: bool = False
    ) -> "OpenAIReasoningProvider":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ProviderUnavailable("OPENAI_API_KEY is not configured")
        return cls(
            api_key=key,
            model=os.environ.get("SAMUEL_OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            base_url=os.environ.get("SAMUEL_OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            allow_action_plan=allow_action_plan,
        )

    def reason(
        self, *, task: str, context: dict[str, Any], attempt: int,
        validation_error: str | None,
    ) -> dict[str, Any]:
        if self.allow_action_plan:
            contract = {
                "output": "one JSON object only",
                "allowed_fields": [
                    "operation", "decision_id",
                    "compatible_with_locked_decisions",
                    "revision_requested", "action_plan", "blocker",
                ],
                "action_plan": (
                    "null or exactly one structured ActionPlan object; use only "
                    "executors and payload shapes present in "
                    "reasoning_context.execution_contracts"
                ),
                "blocker": (
                    "null unless progress is impossible; when non-null identify the "
                    "blocked capability, enumerate equivalent capabilities considered, "
                    "and mark exhausted only after those alternatives are unusable"
                ),
                "no_direct_execution": True,
                "one_action_maximum": True,
            }
            schema = PRODUCTION_ISSUE_REASONING_SCHEMA
        else:
            contract = {
                "output": "one JSON object only",
                "allowed_fields": [
                    "operation", "decision_id",
                    "compatible_with_locked_decisions",
                    "revision_requested", "action_plan", "blocker",
                ],
                "blocker": (
                    "null or typed blocker with capability, alternatives_considered, "
                    "and exhausted"
                ),
                "no_execution": True,
            }
            schema = SHADOW_ISSUE_REASONING_SCHEMA
        prompt = {
            "task": task,
            "attempt": attempt,
            "validation_error": validation_error,
            "reasoning_context": context,
            "contract": contract,
        }
        body = json.dumps({
            "model": self.model,
            "input": json.dumps(prompt, sort_keys=True, separators=(",", ":")),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "samuel_issue_reasoning_proposal",
                    "strict": True,
                    "schema": schema,
                }
            },
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
        if self.allow_action_plan:
            action_plan = decoded.get("action_plan")
            if action_plan is not None and not isinstance(action_plan, dict):
                # Strict structured output should make this unreachable. Keep it
                # parser-visible so StructuredReasoningNode owns bounded repair.
                decoded["action_plan"] = action_plan

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
