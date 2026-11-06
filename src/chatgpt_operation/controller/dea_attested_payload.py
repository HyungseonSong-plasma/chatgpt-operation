"""Deterministic DEA evidence payload v2: created *before* GitHub upload.

GitHub gives an artifact ID only *after* upload. Therefore the signed
subject is a deterministic inner ZIP with no artifact_id. GitHub's outer
download archive and ID are verified independently after upload.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import math
import re
from typing import Any
from zipfile import ZipFile, ZipInfo, ZIP_STORED, BadZipFile

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_REQUIRED = ("execution-manifest.json", "fitness-metrics.json",
             "observations.json", "validation-summary.json")
_SUBJECT_NAME = "dea-evidence.zip"
_MAX_BYTES = 20_000_000
_MAX_JSON_BYTES = 5_000_000


class PayloadContractError(ValueError):
    pass


def _check(ok: bool, reason: str) -> None:
    if not ok:
        raise PayloadContractError(reason)


def _sha(v: Any) -> bool:
    return isinstance(v, str) and bool(_SHA40.fullmatch(v))


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for key, value in pairs:
        _check(key not in d, "duplicate signed JSON key")
        d[key] = value
    return d


def _no_nan(value: str) -> None:
    raise PayloadContractError("nonfinite signed numeric value: " + value)


def _canonical(obj: dict[str, Any]) -> bytes:
    _check(isinstance(obj, dict), "signed document must be an object")
    try:
        return (json.dumps(obj, ensure_ascii=True, sort_keys=True,
                           allow_nan=False, separators=(",", ":")) + "\n").encode()
    except (ValueError, TypeError, OverflowError) as exc:
        raise PayloadContractError("unserializable signed evidence") from exc


def _read_docs(data: bytes) -> tuple[dict[str, Any], dict[str, str]]:
    _check(isinstance(data, bytes) and 0 < len(data) <= _MAX_BYTES,
           "invalid signed ZIP size")
    try:
        with ZipFile(BytesIO(data), "r") as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            _check(len(names) == len(_REQUIRED)
                   and tuple(sorted(names)) == _REQUIRED,
                   "signed payload requires four exact files")
            docs: dict[str, Any] = {}
            hashes: dict[str, str] = {}
            for i in infos:
                mode = (i.external_attr >> 16) & 0o170000
                _check(not i.is_dir() and mode in (0, 0o100000),
                       "unsafe signed ZIP member")
                _check(i.flag_bits & 1 == 0 and 0 < i.file_size <= _MAX_JSON_BYTES,
                       "invalid signed JSON size/encryption")
                raw = z.read(i)
                _check(len(raw) == i.file_size, "decompression mismatch")
                try:
                    obj = json.loads(raw.decode("utf-8"),
                                     object_pairs_hook=_unique_json,
                                     parse_constant=_no_nan)
                except (UnicodeError, ValueError) as exc:
                    raise PayloadContractError("malformed signed JSON") from exc
                _check(isinstance(obj, dict), "signed member must be an object")
                docs[i.filename] = obj
                hashes[i.filename] = sha256(raw).hexdigest()
    except (OSError, RuntimeError, BadZipFile) as exc:
        raise PayloadContractError("invalid signed evidence ZIP") from exc
    return docs, hashes


def build_payload(*, repository: str, run_id: int,
                  candidate_head_sha: str, analyzed_source_sha: str,
                  oracle_revision_sha: str, measurement_set_sha: str,
                  observations: dict[str, Any], metrics: dict[str, Any],
                  summary: dict[str, Any]) -> bytes:
    """Build reproducible signed subject before artifact ID is allocated.

    This can be used by a future *approved* producer; it does not attest
    candidate output origin and does not schedule a workflow.
    """
    _check(isinstance(repository, str) and bool(_REPO.fullmatch(repository)),
           "invalid repository")
    _check(type(run_id) is int and run_id > 0, "invalid run ID")
    _check(all(_sha(s) for s in (candidate_head_sha, analyzed_source_sha,
                                oracle_revision_sha, measurement_set_sha)),
           "all identity SHAs must be exact")
    _check(isinstance(observations, dict)
           and observations.get("source_revision") == analyzed_source_sha,
           "observations must bind analyzed source SHA")
    values = {
        "observations.json": observations,
        "fitness-metrics.json": metrics,
        "validation-summary.json": summary,
    }
    hashes = {name: sha256(_canonical(obj)).hexdigest()
              for name, obj in values.items()}
    values["execution-manifest.json"] = {
        "schema_version": 2, "format": "dea.attestable-evidence.v2",
        "repository": repository, "run_id": run_id,
        "candidate_head_sha": candidate_head_sha,
        "analyzed_source_sha": analyzed_source_sha,
        "oracle_revision_sha": oracle_revision_sha,
        "measurement_set_sha": measurement_set_sha,
        "file_sha256": hashes,
        "artifact_id_binding": "POST_UPLOAD_GITHUB_API",
    }
    b = BytesIO()
    with ZipFile(b, "w", compression=ZIP_STORED) as z:
        for name, obj in sorted(values.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, _canonical(obj))
    result = b.getvalue()
    _check(len(result) <= _MAX_BYTES, "signed subject exceeds limit")
    return result


def inspect_payload(data: bytes, *, repository: str,
                    run_id: int, candidate_head_sha: str,
                    analyzed_source_sha: str,
                    oracle_revision_sha: str,
                    measurement_set_sha: str) -> dict[str, Any]:
    """Read signed subject only after artifact- and attestation verification."""
    docs, hashes = _read_docs(data)
    m = docs["execution-manifest.json"]
    expected = {
        "schema_version": 2,
        "format": "dea.attestable-evidence.v2",
        "repository": repository, "run_id": run_id,
        "candidate_head_sha": candidate_head_sha,
        "analyzed_source_sha": analyzed_source_sha,
        "oracle_revision_sha": oracle_revision_sha,
        "measurement_set_sha": measurement_set_sha,
        "artifact_id_binding": "POST_UPLOAD_GITHUB_API",
    }
    _check(all(m.get(k) == v for k, v in expected.items()),
           "signed payload identity/protocol mismatch")
    asserted = m.get("file_sha256")
    _check(isinstance(asserted, dict)
           and set(asserted) == set(_REQUIRED) - {"execution-manifest.json"},
           "signed member checksum set mismatch")
    _check(all(asserted[n] == hashes[n] for n in asserted),
           "signed inner member checksum mismatch")
    _check(docs["observations.json"].get("source_revision") == analyzed_source_sha,
           "signed observation source mismatch")
    return {
        "status": "SIGNED_SUBJECT_CONTENT_VALID",
        "payload_sha256": sha256(data).hexdigest(),
        "manifest": m, "observations": docs["observations.json"],
        "metrics": docs["fitness-metrics.json"],
        "summary": docs["validation-summary.json"],
        "artifact_id": None,
        "producer_attestation": "NOT_YET_VERIFIED",
        "semantic_accuracy": "NOT_YET_EVALUATED",
        "automatic_fitness_pass": False,
    }


def unwrap_github_artifact_zip(
    downloaded_zip: bytes, *, expected_outer_digest: str,
    expected_outer_size: int,
) -> bytes:
    """Return signed inner ZIP. Never confuse GitHub outer ZIP with subject.

    Uploaded artifact contains exactly one dea-evidence.zip file. Its GitHub
    artifact ID/digest are confirmed separately using trusted REST readback.
    """
    _check(isinstance(downloaded_zip, bytes)
           and 0 < len(downloaded_zip) <= _MAX_BYTES,
           "invalid downloaded artifact size")
    _check(type(expected_outer_size) is int
           and expected_outer_size == len(downloaded_zip),
           "GitHub outer ZIP byte count mismatch")
    _check(isinstance(expected_outer_digest, str)
           and bool(re.fullmatch(r"[0-9a-f]{64}", expected_outer_digest))
           and sha256(downloaded_zip).hexdigest() == expected_outer_digest,
           "GitHub outer ZIP digest mismatch")
    try:
        with ZipFile(BytesIO(downloaded_zip)) as z:
            infos = z.infolist()
            _check(len(infos) == 1 and infos[0].filename == _SUBJECT_NAME,
                   "unexpected GitHub artifact ZIP member set")
            entry = infos[0]
            mode = (entry.external_attr >> 16) & 0o170000
            _check(mode in (0, 0o100000) and not entry.is_dir()
                   and entry.flag_bits & 1 == 0
                   and 0 < entry.file_size <= _MAX_BYTES,
                   "unsafe GitHub artifact member")
            subject = z.read(entry)
            _check(len(subject) == entry.file_size,
                   "signed subject decompression mismatch")
            return subject
    except (BadZipFile, RuntimeError, OSError) as exc:
        raise PayloadContractError("invalid GitHub ZIP wrapper") from exc
