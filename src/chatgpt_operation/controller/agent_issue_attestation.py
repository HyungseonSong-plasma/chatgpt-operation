"""Independently authenticated GitHub run+artifact verification for Child receipts.

The untrusted Child comment supplies a run ID, not proof. Only the raw
GitHub API run, a unique non-expired ZIP and exact manifest content can
attest it. Source artifacts are trusted only for provenance; semantic
correctness still needs independently approved gates.
"""
from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Callable, Mapping, Protocol
from zipfile import BadZipFile, ZipFile

from .agent_issue_partition import AgentIssueError, validate_receipt

WORKFLOW = "samuel-agent-child-evidence.yml"
ARTIFACT_PREFIX = "samuel-agent-child-evidence-"
_MAX_ARCHIVE = 800_000
_MAX_MANIFEST = 180_000


class AgentEvidenceError(AgentIssueError):
    pass


class GithubRunReader(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


def _from_zip(archive: bytes) -> dict[str, Any]:
    if type(archive) is not bytes or not 0 < len(archive) <= _MAX_ARCHIVE:
        raise AgentEvidenceError("empty or oversized evidence ZIP")
    try:
        with ZipFile(io.BytesIO(archive)) as zipped:
            files = zipped.infolist()
            if len(files) != 1 or files[0].filename != "agent-receipt.json":
                raise AgentEvidenceError("evidence archive has unexpected members")
            file = files[0]
            if file.is_dir() or not 0 < file.file_size <= _MAX_MANIFEST:
                raise AgentEvidenceError("evidence manifest exceeds safe limit")
            raw = zipped.read(file)
            if len(raw) != file.file_size:
                raise AgentEvidenceError("evidence manifest length mismatch")
        manifest = json.loads(raw.decode("utf-8"))
    except (BadZipFile, UnicodeError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        raise AgentEvidenceError("unable to decode evidence ZIP") from exc
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "receipt"}
        or manifest["schema_version"] != 1
    ):
        raise AgentEvidenceError("invalid source evidence schema")
    return manifest


def verify_authenticated_child_receipt(
    receipt: dict[str, Any],
    *,
    reader: GithubRunReader,
    fetch_artifact_zip: Callable[[int], bytes],
    repository: str,
    trusted_actor: str,
    approved_workflow: str = WORKFLOW,
) -> dict[str, Any]:
    """Return the contract consumed by reduce_child_progress.verify_source.

    The reader/fetcher MUST use independently authenticated GitHub API calls;
    never use a worker-supplied archive URL or JSON as the verifier source.
    """
    r = validate_receipt(receipt)
    if not trusted_actor or repository.count("/") != 1:
        raise AgentEvidenceError("independent source policy missing")
    if approved_workflow != WORKFLOW:
        raise AgentEvidenceError("unexpected evidence producer workflow")
    rid = r["source_run_id"]
    origin = reader.get(f"/actions/runs/{rid}")
    if not isinstance(origin, dict):
        raise AgentEvidenceError("GitHub execution origin is missing")
    owner = origin.get("actor")
    repo = origin.get("repository")
    path = origin.get("path")
    if not (
        type(origin.get("id")) is int and origin["id"] == rid
        and isinstance(owner, dict) and owner.get("login") == trusted_actor
        and isinstance(repo, dict) and repo.get("full_name") == repository
        and isinstance(path, str)
        and path.split("@", 1)[0] == ".github/workflows/" + approved_workflow
        and origin.get("event") == "workflow_dispatch"
        and origin.get("head_branch") == "main"
        and origin.get("head_sha") == r["source_head_sha"]
        and origin.get("status") == "completed"
        and origin.get("conclusion") == "success"
        and type(origin.get("run_attempt")) is int
        and origin["run_attempt"] == 1
    ):
        raise AgentEvidenceError("untrusted GitHub run identity or unsuccessful status")

    artifact_name = ARTIFACT_PREFIX + str(rid)
    artifact_result = reader.get(
        f"/actions/runs/{rid}/artifacts",
        query={"name": artifact_name, "per_page": "100"},
    )
    if (
        not isinstance(artifact_result, dict)
        or artifact_result.get("total_count") != 1
        or not isinstance(artifact_result.get("artifacts"), list)
        or len(artifact_result["artifacts"]) != 1
    ):
        raise AgentEvidenceError("source evidence artifact absent or ambiguous")
    entry = artifact_result["artifacts"][0]
    if not (
        isinstance(entry, dict)
        and type(entry.get("id")) is int
        and entry["id"] > 0
        and entry.get("name") == artifact_name
        and entry.get("expired") is False
        and isinstance(entry.get("workflow_run"), dict)
        and entry["workflow_run"].get("id") == rid
    ):
        raise AgentEvidenceError("source evidence artifact identity mismatch")
    if not callable(fetch_artifact_zip):
        raise AgentEvidenceError("independent artifact reader required")
    raw = fetch_artifact_zip(entry["id"])
    if type(raw) is not bytes:
        raise AgentEvidenceError("artifact reader must return authenticated ZIP bytes")
    digest = hashlib.sha256(raw).hexdigest()
    api_digest = entry.get("digest")
    if api_digest is not None and api_digest != "sha256:" + digest:
        raise AgentEvidenceError("GitHub artifact digest mismatch")
    manifest = _from_zip(raw)
    observed = validate_receipt(manifest["receipt"])
    if observed != r:
        raise AgentEvidenceError("artifact evidence differs from Child receipt")
    return {
        "receipt_id": r["receipt_id"],
        "source_run_id": rid,
        "source_head_sha": r["source_head_sha"],
        "detail_sha256": r["detail_sha256"],
        "outcome": r["outcome"],
        "verified": True,
        "github_artifact_sha256": digest,
    }
