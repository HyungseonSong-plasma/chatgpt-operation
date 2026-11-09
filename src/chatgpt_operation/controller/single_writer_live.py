"""Live, read-only evidence verification and bounded Issue-comment enumeration.

No mutations are performed. GitHub REST identities and artifact ZIP bytes are
independently retrieved by a trusted writer; worker claims grant no authority.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any, Callable, Mapping, Protocol
from zipfile import BadZipFile, ZipFile

from .single_writer_pilot import (
    SingleWriterError, plan_progress_write, read_inbox, validate_intent,
)

_MAX_ARCHIVE = 600_000
_MAX_MANIFEST = 200_000
_MAX_COMMENTS = 2000
_MAX_PAGES = 21
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MANIFEST = frozenset({
    "schema_version", "work_id", "unit_id", "input_sha256",
    "outcome", "detail_sha256", "detail", "head_sha",
    "workflow_run_id", "run_attempt", "plan_sha256", "policy_sha256",
})


class LiveEvidenceError(SingleWriterError):
    """An external fact was missing, contradictory, or unverifiable."""


class GithubRead(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


def _safe_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not re.fullmatch(r"[A-Za-z0-9._-]+", value)
        or value.startswith(".")
        or not value.endswith(".yml")
    ):
        raise LiveEvidenceError("unsafe workflow name")
    return value


def read_stable_issue_comments(
    transport: GithubRead, *, issue_number: int,
) -> list[dict[str, Any]]:
    """Read a complete, stable bounded snapshot; fail closed on pagination races.

    This does NOT lock the Issue. Only a serialized writer may commit state.
    """
    if type(issue_number) is not int or issue_number <= 0:
        raise LiveEvidenceError("invalid issue number")

    def snapshot() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[int] = set()
        for page in range(1, _MAX_PAGES + 1):
            rows = transport.get(
                f"/issues/{issue_number}/comments",
                query={"per_page": "100", "page": str(page)},
            )
            if not isinstance(rows, list) or len(rows) > 100:
                raise LiveEvidenceError("incomplete or invalid GitHub comment page")
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or type(row.get("id")) is not int
                    or row["id"] < 1
                    or not isinstance(row.get("body"), str)
                    or not isinstance(row.get("user"), dict)
                ):
                    raise LiveEvidenceError("malformed GitHub comment record")
                if row["id"] in seen:
                    raise LiveEvidenceError("duplicate ID across comment pages")
                seen.add(row["id"])
                result.append(row)
            if len(result) > _MAX_COMMENTS:
                raise LiveEvidenceError("comment inventory exceeds safety bound")
            if len(rows) < 100:
                return result
        raise LiveEvidenceError("comment pagination did not terminate")

    first = snapshot()
    second = snapshot()
    if [(x["id"], x["body"], x["user"].get("login")) for x in first] != [
        (x["id"], x["body"], x["user"].get("login")) for x in second
    ]:
        raise LiveEvidenceError("Issue comments changed during read-only inventory")
    return second


def _manifest_from_zip(archive: bytes) -> dict[str, Any]:
    if not isinstance(archive, bytes) or not 0 < len(archive) <= _MAX_ARCHIVE:
        raise LiveEvidenceError("artifact archive missing or exceeds bound")
    try:
        with ZipFile(io.BytesIO(archive)) as zipped:
            entries = zipped.infolist()
            if len(entries) != 1 or entries[0].filename != "progress-evidence.json":
                raise LiveEvidenceError("artifact must contain exactly one trusted manifest")
            info = entries[0]
            if info.is_dir() or info.file_size > _MAX_MANIFEST or info.file_size < 1:
                raise LiveEvidenceError("artifact manifest unbounded")
            raw = zipped.read(info)
            if len(raw) != info.file_size:
                raise LiveEvidenceError("artifact manifest length mismatch")
        manifest = json.loads(raw.decode("utf-8"))
    except (BadZipFile, UnicodeError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        raise LiveEvidenceError("artifact manifest unreadable") from exc
    if not isinstance(manifest, dict) or set(manifest) != _ALLOWED_MANIFEST:
        raise LiveEvidenceError("unrecognized artifact manifest schema")
    if manifest["schema_version"] != 1 or manifest["run_attempt"] != 1:
        raise LiveEvidenceError("unsupported evidence manifest or rerun")
    return manifest


def verify_github_progress_source(
    intent: dict[str, Any],
    *,
    transport: GithubRead,
    read_artifact_zip: Callable[[int], bytes],
    expected_repository: str,
    trusted_workflows: frozenset[str],
    trusted_actor: str,
    approved_main_sha: str,
) -> dict[str, Any]:
    """Attest a typed success receipt using authenticated GitHub API + ZIP.

    The caller must pin approved_main_sha from reviewed, trusted origin state.
    The artifact proves workflow output, not semantic correctness of analysis.
    """
    proposal = validate_intent(intent)
    source = proposal["source"]
    repository = source["repository"]
    if (
        not expected_repository
        or repository != expected_repository
        or source["workflow"] not in trusted_workflows
    ):
        raise LiveEvidenceError("unapproved source repository or workflow")
    workflow = _safe_path(source["workflow"])
    if not re.fullmatch(r"[0-9a-f]{40}", approved_main_sha):
        raise LiveEvidenceError("approved main commit must be pinned")
    if source["head_sha"] != approved_main_sha:
        raise LiveEvidenceError("unapproved source commit")
    if not trusted_actor:
        raise LiveEvidenceError("trusted run actor required")
    rid = source["run_id"]
    path = "/repos/" + repository
    run = transport.get(path + f"/actions/runs/{rid}")
    if not isinstance(run, dict):
        raise LiveEvidenceError("authenticated workflow run unavailable")
    actor = run.get("actor")
    run_repo = run.get("repository")
    run_path = run.get("path")
    expected_path = ".github/workflows/" + workflow
    if not (
        type(run.get("id")) is int and run["id"] == rid
        and isinstance(run_repo, dict)
        and run_repo.get("full_name") == repository
        and isinstance(actor, dict)
        and actor.get("login") == trusted_actor
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main"
        and run.get("head_sha") == approved_main_sha
        and isinstance(run_path, str)
        and run_path.split("@", 1)[0] == expected_path
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] == 1
    ):
        raise LiveEvidenceError("source workflow origin or terminal status mismatched")
    name = f"samuel-progress-evidence-{rid}"
    artifact_list = transport.get(
        path + f"/actions/runs/{rid}/artifacts",
        query={"name": name, "per_page": "100"},
    )
    if (
        not isinstance(artifact_list, dict)
        or artifact_list.get("total_count") != 1
        or not isinstance(artifact_list.get("artifacts"), list)
        or len(artifact_list["artifacts"]) != 1
    ):
        raise LiveEvidenceError("expected exactly one named source artifact")
    item = artifact_list["artifacts"][0]
    if not (
        isinstance(item, dict)
        and type(item.get("id")) is int and item["id"] > 0
        and item.get("name") == name
        and item.get("expired") is False
        and isinstance(item.get("workflow_run"), dict)
        and item["workflow_run"].get("id") == rid
    ):
        raise LiveEvidenceError("artifact identity or expiry mismatch")
    archive = read_artifact_zip(item["id"])
    if not isinstance(archive, bytes):
        raise LiveEvidenceError("authenticated archive reader returned invalid bytes")
    checksum = hashlib.sha256(archive).hexdigest()
    if checksum != source["artifact_sha256"]:
        raise LiveEvidenceError("independent archive checksum mismatch")
    api_digest = item.get("digest")
    if api_digest is not None and api_digest != "sha256:" + checksum:
        raise LiveEvidenceError("GitHub artifact digest mismatch")
    manifest = _manifest_from_zip(archive)
    for field in ("work_id", "unit_id", "input_sha256", "outcome", "detail_sha256"):
        if manifest.get(field) != proposal[field]:
            raise LiveEvidenceError("manifest result identity mismatch")
    if (
        manifest.get("head_sha") != approved_main_sha
        or manifest.get("workflow_run_id") != rid
        or manifest.get("plan_sha256") != proposal["plan_sha256"]
        or manifest.get("policy_sha256") != proposal["policy_sha256"]
    ):
        raise LiveEvidenceError("manifest source/plan/policy mismatch")
    canonical = json.dumps(
        manifest["detail"], sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != proposal["detail_sha256"]:
        raise LiveEvidenceError("manifest detailed evidence checksum mismatch")
    return {
        **source,
        "conclusion": "success",
        "work_id": proposal["work_id"],
        "unit_id": proposal["unit_id"],
        "input_sha256": proposal["input_sha256"],
        "outcome": proposal["outcome"],
        "detail_sha256": proposal["detail_sha256"],
    }

def qualify_next_inbox_request(
    transport: GithubRead,
    *,
    issue_number: int,
    read_artifact_zip: Callable[[int], bytes],
    trusted_comment_authors: frozenset[str],
    trusted_actor: str,
    expected_repository: str,
    trusted_workflows: frozenset[str],
    approved_main_sha: str,
    live_gate_states: Mapping[str, str],
) -> dict[str, Any]:
    """Find the first independently verified request, with no Issue mutations.

    The caller is an exclusive writer; the returned write request is only
    a proposal and MUST pass persist_state_write() precondition + readback.
    """
    comments = read_stable_issue_comments(transport, issue_number=issue_number)
    inbox = read_inbox(comments, trusted_authors=trusted_comment_authors)
    if not inbox:
        return {"status": "IDLE", "request_id": None, "state_write": None}
    for intent in inbox:
        verified = lambda _source: verify_github_progress_source(
            intent,
            transport=transport,
            read_artifact_zip=read_artifact_zip,
            expected_repository=expected_repository,
            trusted_workflows=trusted_workflows,
            trusted_actor=trusted_actor,
            approved_main_sha=approved_main_sha,
        )
        proposal = plan_progress_write(
            comments, intent,
            verify_source=verified,
            allowed_repository=expected_repository,
            allowed_workflows=trusted_workflows,
            live_gate_states=live_gate_states,
        )
        if proposal["status"] == "ALREADY_APPLIED":
            continue
        return proposal
    return {"status": "COMPLETE", "request_id": None, "state_write": None}
