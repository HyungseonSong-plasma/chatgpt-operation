"""Isolated single-writer intake/planning for existing Samuel ResearchState.

All request comments are UNTRUSTED proposals. This module only produces a
transport-neutral state-write request; it never writes, dispatches or claims
that a GitHub Issue comment PATCH is atomic. A trusted, exclusive writer must
verify source evidence independently before calling plan_progress_write().
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .durable_state import load_state_comment, state_write_request
from .progress_resume import (
    ProgressResumeError, detail_digest, record_verified_unit, validate_checkpoint,
)

INBOX_MARKER = "<!-- samuel-state-write-intent-v1:"
_ENVELOPE = re.compile(
    r"\A<!-- samuel-state-write-intent-v1:([0-9a-f]{64}) -->\n"
    r"```json\n(.*?)\n```\Z", re.DOTALL
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED = frozenset({
    "schema_version", "request_id", "work_id", "base_revision",
    "plan_sha256", "policy_sha256", "unit_id", "input_sha256",
    "outcome", "detail", "detail_sha256", "source",
})
_SOURCE = frozenset({
    "repository", "run_id", "head_sha", "artifact_sha256", "workflow",
})
_MAX_REQUEST_BYTES = 220_000
_MAX_INBOX = 100


class SingleWriterError(ValueError):
    """Invalid proposal, stale authority, or unverifiable evidence."""


def _canonical(data: Any) -> bytes:
    try:
        text = json.dumps(
            data, sort_keys=True, separators=(",", ":"),
            allow_nan=False, ensure_ascii=False,
        )
        if json.loads(text) != data:
            raise SingleWriterError("lossy JSON input")
        return text.encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SingleWriterError("request is not canonical JSON") from exc


def _sha(value: Any, what: str, pattern: re.Pattern[str] = _SHA256) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise SingleWriterError(what + " must be a lowercase hash")
    return value


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise SingleWriterError(what + " must be a bounded nonempty string")
    return value


def validate_intent(raw: Any) -> dict[str, Any]:
    """Validate the bounded, deterministic envelope; grant NO authority."""
    if not isinstance(raw, dict) or set(raw) != _ALLOWED:
        raise SingleWriterError("invalid request envelope")
    if raw["schema_version"] != 1:
        raise SingleWriterError("unsupported request version")
    _text(raw["work_id"], "work_id")
    _text(raw["unit_id"], "unit_id")
    if type(raw["base_revision"]) is not int or raw["base_revision"] < 1:
        raise SingleWriterError("invalid base_revision")
    for field in ("plan_sha256", "policy_sha256", "input_sha256", "detail_sha256"):
        _sha(raw[field], field)
    if raw["outcome"] not in ("PASS", "NOOP"):
        raise SingleWriterError("unsuccessful work is not a complete receipt")
    if raw["detail_sha256"] != detail_digest(raw["detail"]):
        raise SingleWriterError("detail digest mismatch")
    src = raw["source"]
    if not isinstance(src, dict) or set(src) != _SOURCE:
        raise SingleWriterError("invalid source identity")
    _text(src["repository"], "source repository")
    _text(src["workflow"], "source workflow")
    if (
        type(src["run_id"]) is not int or src["run_id"] < 1
        or "/" not in src["repository"]
    ):
        raise SingleWriterError("invalid source run identity")
    _sha(src["head_sha"], "source head", _SHA40)
    _sha(src["artifact_sha256"], "artifact digest")
    if len(_canonical(raw)) > _MAX_REQUEST_BYTES:
        raise SingleWriterError("request exceeds bounded envelope")
    expected = hashlib.sha256(_canonical({
        k: v for k, v in raw.items() if k != "request_id"
    })).hexdigest()
    if _sha(raw["request_id"], "request_id") != expected:
        raise SingleWriterError("request id does not match immutable content")
    return json.loads(_canonical(raw))


def create_intent(
    *, work_id: str, base_revision: int, plan_sha256: str,
    policy_sha256: str, unit_id: str, input_sha256: str, outcome: str,
    detail: Any, source: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "work_id": work_id,
        "base_revision": base_revision,
        "plan_sha256": plan_sha256,
        "policy_sha256": policy_sha256,
        "unit_id": unit_id,
        "input_sha256": input_sha256,
        "outcome": outcome,
        "detail": detail,
        "detail_sha256": detail_digest(detail),
        "source": source,
    }
    payload["request_id"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return validate_intent(payload)


def encode_inbox_comment(intent: dict[str, Any]) -> str:
    raw = validate_intent(intent)
    return (
        INBOX_MARKER + raw["request_id"] + " -->\n```json\n"
        + _canonical(raw).decode("utf-8") + "\n```"
    )


def decode_inbox_comment(body: Any) -> dict[str, Any]:
    if not isinstance(body, str):
        raise SingleWriterError("inbox comment body must be text")
    match = _ENVELOPE.fullmatch(body)
    if match is None:
        raise SingleWriterError("inbox comment marker or fence is invalid")
    try:
        raw = json.loads(match.group(2))
    except json.JSONDecodeError as exc:
        raise SingleWriterError("inbox JSON is invalid") from exc
    intent = validate_intent(raw)
    if match.group(1) != intent["request_id"]:
        raise SingleWriterError("inbox marker identity mismatch")
    return intent


def read_inbox(
    comments: Sequence[dict[str, Any]], *, trusted_authors: frozenset[str],
) -> list[dict[str, Any]]:
    """Read bounded pending proposals. Author provenance is necessary, not sufficient.

    This method may only be called after COMPLETE paginated Issue comment
    enumeration. Incomplete comment pages must hard-stop the caller.
    """
    if not trusted_authors:
        raise SingleWriterError("trusted author allowlist required")
    items: dict[str, dict[str, Any]] = {}
    for comment in comments:
        if not isinstance(comment, dict):
            raise SingleWriterError("invalid Issue comment")
        body = comment.get("body")
        if not isinstance(body, str) or INBOX_MARKER not in body:
            continue
        user = comment.get("user")
        if (
            not isinstance(user, dict)
            or user.get("login") not in trusted_authors
        ):
            raise SingleWriterError("untrusted inbox comment author")
        intent = decode_inbox_comment(body)
        if intent["request_id"] in items:
            if items[intent["request_id"]] != intent:
                raise SingleWriterError("conflicting duplicate request id")
        else:
            items[intent["request_id"]] = intent
        if len(items) > _MAX_INBOX:
            raise SingleWriterError("inbox capacity exceeded")
    return list(items.values())


def plan_progress_write(
    comments: list[dict[str, Any]],
    intent: dict[str, Any],
    *,
    verify_source: Callable[[dict[str, Any]], Mapping[str, Any]],
    allowed_repository: str,
    allowed_workflows: frozenset[str],
    live_gate_states: Mapping[str, str],
) -> dict[str, Any]:
    """One read-only write proposal using current authoritative state.

    verify_source MUST independently acquire the GitHub run/artifact evidence.
    Its return value is not allowed to originate from the worker's JSON.
    """
    raw = validate_intent(intent)
    state = load_state_comment(comments)
    if state is None or state.progress_checkpoint is None:
        raise SingleWriterError("structured authoritative ResearchState missing")
    if state.research_id != raw["work_id"]:
        raise SingleWriterError("work identity mismatch")
    if state.action_queue or state.diagnostic_recoveries:
        raise SingleWriterError("active execution/recovery state forbids pilot merge")
    cp = validate_checkpoint(state.progress_checkpoint)
    if cp["plan_sha256"] != raw["plan_sha256"] or cp["policy_sha256"] != raw["policy_sha256"]:
        raise SingleWriterError("plan or policy advanced")
    if raw["base_revision"] > state.revision:
        raise SingleWriterError("request was created from a future revision")
    if raw["source"]["repository"] != allowed_repository:
        raise SingleWriterError("unapproved evidence repository")
    if raw["source"]["workflow"] not in allowed_workflows:
        raise SingleWriterError("unapproved evidence workflow")
    if not isinstance(live_gate_states, Mapping):
        raise SingleWriterError("writer gate states must be authoritative")
    if not callable(verify_source):
        raise SingleWriterError("independent source verifier is mandatory")
    trusted = verify_source(dict(raw["source"]))
    if not isinstance(trusted, Mapping):
        raise SingleWriterError("source verifier returned invalid evidence")
    if trusted.get("conclusion") != "success":
        raise SingleWriterError("source run is not successfully complete")
    for field in _SOURCE:
        if trusted.get(field) != raw["source"][field]:
            raise SingleWriterError("source run identity or artifact mismatch")
    for field in ("work_id", "unit_id", "input_sha256", "outcome", "detail_sha256"):
        if trusted.get(field) != raw[field]:
            raise SingleWriterError("source evidence does not attest requested result")
    # Do not accept worker-submitted gates, policy or evidence conclusions.
    try:
        proposal = record_verified_unit(
            state,
            unit_id=raw["unit_id"],
            input_sha256=raw["input_sha256"],
            outcome=raw["outcome"],
            detail=raw["detail"],
            gate_states=live_gate_states,
        )
    except ProgressResumeError as exc:
        raise SingleWriterError("progress is not safely applicable: " + str(exc)) from exc
    if proposal.revision == state.revision:
        return {
            "status": "ALREADY_APPLIED",
            "request_id": raw["request_id"],
            "based_on_revision": state.revision,
            "state_write": None,
        }
    return {
        "status": "WRITE_PROPOSAL",
        "request_id": raw["request_id"],
        "based_on_revision": state.revision,
        "state_write": state_write_request(comments, proposal),
    }
