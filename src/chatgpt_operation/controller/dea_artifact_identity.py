"""DEA v0.2 read-only GitHub Actions artifact identity and archive checks.

GitHub API metadata and the archive MUST be fetched independently by an
authorized caller. This module checks their consistency; it does not certify
the archive-producing job or any claimed semantic/fitness result.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import re
from typing import Any
from zipfile import BadZipFile, ZipFile

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED = frozenset({
    "execution-manifest.json", "observations.json",
    "fitness-metrics.json", "validation-summary.json",
})
_MAX_ARCHIVE_BYTES = 25_000_000
_MAX_FILE_BYTES = 8_000_000
_MAX_TOTAL_BYTES = 40_000_000


class ArtifactEvidenceError(ValueError):
    """Malformed or untrustworthy identity, archive, or evidence."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactEvidenceError(message)


def _integer(value: Any) -> bool:
    return type(value) is int and value > 0


def _sha40(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA40.fullmatch(value))


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def _safe_file_name(name: Any) -> bool:
    return (isinstance(name, str) and name in _REQUIRED
            and not name.startswith("/") and "\\" not in name)


def verify_github_artifact_listing(
    *, run: dict[str, Any], listing: dict[str, Any],
    repository: str, expected_head_sha: str,
    run_id: int, artifact_id: int, artifact_name: str,
) -> dict[str, Any]:
    """Verify that a unique, unexpired artifact belongs to the pinned run.

    No producer-job attribution can be inferred from GitHub's artifact list.
    A truncated/paginated listing is not evidence of uniqueness.
    """
    _require(isinstance(run, dict) and isinstance(listing, dict),
             "run and listing must be independently obtained mappings")
    _require(isinstance(repository, str) and "/" in repository,
             "missing expected repository")
    _require(_sha40(expected_head_sha), "invalid expected candidate head SHA")
    _require(_integer(run_id) and _integer(artifact_id), "invalid run/artifact ID")
    _require(isinstance(artifact_name, str) and bool(artifact_name.strip()),
             "artifact name required")
    repo = run.get("repository")
    _require(isinstance(repo, dict) and repo.get("full_name") == repository,
             "run repository mismatch")
    _require(_integer(repo.get("id")), "missing trusted repository id")
    _require(run.get("id") == run_id and run.get("head_sha") == expected_head_sha,
             "run id/head mismatch")
    _require(run.get("status") == "completed" and run.get("conclusion") == "success",
             "Actions run not successful")
    items = listing.get("artifacts")
    _require(isinstance(items, list)
             and type(listing.get("total_count")) is int
             and listing["total_count"] == len(items),
             "incomplete artifact listing or pagination")
    ids = [a.get("id") for a in items if isinstance(a, dict)]
    _require(len(ids) == len(items) and len(set(ids)) == len(ids)
             and all(_integer(i) for i in ids),
             "invalid/duplicate listed artifact identities")
    matched = [a for a in items if a["id"] == artifact_id]
    _require(len(matched) == 1, "expected artifact id not present")
    a = matched[0]
    _require(a.get("name") == artifact_name, "artifact name mismatch")
    _require(a.get("expired") is False, "expired artifact cannot be verified")
    _require(_integer(a.get("size_in_bytes"))
             and a["size_in_bytes"] <= _MAX_ARCHIVE_BYTES,
             "invalid or excessive artifact size")
    digest = a.get("digest")
    _require(isinstance(digest, str) and digest.startswith("sha256:")
             and _sha256(digest[7:]), "missing SHA-256 artifact digest")
    origin = a.get("workflow_run")
    _require(isinstance(origin, dict)
             and origin.get("id") == run_id
             and origin.get("head_sha") == expected_head_sha,
             "artifact workflow run/head identity mismatch")
    _require(origin.get("repository_id") == repo["id"],
             "artifact source repository ID mismatch")
    return {
        "status": "METADATA_IDENTITY_MATCH",
        "artifact_id": artifact_id, "artifact_name": artifact_name,
        "run_id": run_id, "candidate_head_sha": expected_head_sha,
        "archive_digest_sha256": digest[7:],
        "artifact_size_bytes": a["size_in_bytes"],
        "producer_job_attribution": "NOT_ATTESTED",
        "workflow_integrity": "NOT_ATTESTED",
        "repository_mutation_authorized": False,
    }


def verify_artifact_zip(
    archive: bytes, *, expected_sha256: str,
    expected_size_bytes: int, run_id: int, artifact_id: int,
    candidate_head_sha: str, analyzed_source_sha: str,
) -> dict[str, Any]:
    """Hash ZIP bytes and validate closed, bounded evidence file set.

    Checks are independent of manifest claims but not cryptographic proof
    of the job that produced the archive. A ZIP file cannot self-sign.
    """
    _require(isinstance(archive, bytes) and 0 < len(archive) <= _MAX_ARCHIVE_BYTES,
             "invalid archive bytes or size")
    _require(_sha256(expected_sha256), "expected artifact digest required")
    _require(type(expected_size_bytes) is int
             and expected_size_bytes == len(archive),
             "downloaded artifact byte size mismatch")
    _require(sha256(archive).hexdigest() == expected_sha256,
             "artifact archive SHA-256 mismatch")
    _require(_integer(run_id) and _integer(artifact_id)
             and _sha40(candidate_head_sha) and _sha40(analyzed_source_sha),
             "invalid pinned identities")
    try:
        with ZipFile(BytesIO(archive), "r") as z:
            members = z.infolist()
            names = [entry.filename for entry in members]
            _require(len(members) == len(_REQUIRED)
                     and set(names) == _REQUIRED
                     and len(names) == len(set(names)),
                     "archive must contain exact evidence file set")
            _require(all(_safe_file_name(name) for name in names),
                     "unsafe archive member name")
            total = 0
            docs: dict[str, Any] = {}
            digests: dict[str, str] = {}
            for entry in members:
                mode = (entry.external_attr >> 16) & 0o170000
                _require(not entry.is_dir() and mode in (0, 0o100000),
                         "non-regular ZIP member")
                _require(entry.flag_bits & 0x1 == 0, "encrypted ZIP member")
                _require(0 <= entry.file_size <= _MAX_FILE_BYTES,
                         "unbounded evidence member")
                total += entry.file_size
                _require(total <= _MAX_TOTAL_BYTES, "archive expands excessively")
                data = z.read(entry)
                _require(len(data) == entry.file_size,
                         "archive member decompression mismatch")
                digests[entry.filename] = sha256(data).hexdigest()
                try:
                    docs[entry.filename] = json.loads(data.decode("utf-8"))
                except (UnicodeError, ValueError) as exc:
                    raise ArtifactEvidenceError("malformed evidence JSON") from exc
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise ArtifactEvidenceError("unreadable ZIP evidence archive") from exc
    manifest = docs["execution-manifest.json"]
    _require(isinstance(manifest, dict) and manifest.get("schema_version") == 1,
             "invalid execution manifest")
    _require(manifest.get("run_id") == run_id
             and manifest.get("artifact_id") == artifact_id
             and manifest.get("candidate_head_sha") == candidate_head_sha
             and manifest.get("analyzed_source_sha") == analyzed_source_sha,
             "execution-manifest pinned identity mismatch")
    hashes = manifest.get("file_sha256")
    _require(isinstance(hashes, dict)
             and set(hashes) == _REQUIRED - {"execution-manifest.json"},
             "manifest content digest coverage mismatch")
    for name, expected in hashes.items():
        _require(_sha256(expected) and expected == digests[name],
                 "file SHA-256 mismatch: " + name)
    _require(isinstance(docs["observations.json"], dict),
             "observations must be an object")
    _require(isinstance(docs["fitness-metrics.json"], dict),
             "fitness metrics must be an object")
    _require(isinstance(docs["validation-summary.json"], dict),
             "validation summary must be an object")
    return {
        "status": "ARCHIVE_CONTENT_MATCH",
        "manifest": manifest,
        "observations": docs["observations.json"],
        "metrics": docs["fitness-metrics.json"],
        "summary": docs["validation-summary.json"],
        "archive_digest_sha256": expected_sha256,
        "file_sha256": digests,
        "producer_job_attribution": "NOT_ATTESTED",
        "semantic_correctness": "NOT_EVALUATED",
        "repository_mutation_authorized": False,
    }
