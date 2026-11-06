"""Human-review routing for untrusted DEA evidence without accidental promotion.

A validation failure is NOT silently discarded: publish a deterministic,
sanitized review packet for an authorized human. Unsafe data remains unparsed.
This module never turns a failed gate into PASS and does not grant mutation.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_PHASES = frozenset({
    "ACQUISITION", "RUN_IDENTITY", "ARTIFACT_IDENTITY",
    "ARCHIVE_INTEGRITY", "PRODUCER_ATTESTATION",
    "SEMANTIC_ORACLE", "FITNESS_GATES",
})
_CATEGORIES = frozenset({
    "MISSING_EVIDENCE", "WRONG_IDENTITY", "EXPIRED_EVIDENCE",
    "INTEGRITY_MISMATCH", "UNSAFE_ARCHIVE", "UNSUPPORTED_FORMAT",
    "SEMANTIC_DIFFERENCE", "PRODUCER_UNVERIFIED",
    "POLICY_OR_PERMISSION", "UNEXPECTED_VERIFICATION_ERROR",
})


class ReviewRoutingError(ValueError):
    pass


def _check(value: bool, reason: str) -> None:
    if not value:
        raise ReviewRoutingError(reason)


def make_review_packet(
    *, repository: str, candidate_head_sha: str,
    phase: str, category: str,
    run_id: int | None = None, artifact_id: int | None = None,
    analyzed_source_sha: str | None = None,
    expected_archive_digest: str | None = None,
    observed_archive_digest: str | None = None,
    evidence_kind: str = "GITHUB_ACTIONS_ARTIFACT",
) -> dict[str, Any]:
    """Create a review task from verifier-owned identities, not candidate JSON.

    Packet includes no raw archive bytes, unsafe path, token, network error
    body, or unverifiable PASS claim. Original Artifact remains available in
    GitHub where present; retention/backup is an independent owner concern.
    """
    _check(isinstance(repository, str) and bool(_REPO.fullmatch(repository)),
           "invalid repository identity")
    _check(isinstance(candidate_head_sha, str)
           and bool(_SHA40.fullmatch(candidate_head_sha)),
           "exact candidate HEAD required")
    _check(phase in _PHASES and category in _CATEGORIES,
           "unsupported review phase or category")
    _check(run_id is None or type(run_id) is int and run_id > 0,
           "invalid run ID")
    _check(artifact_id is None or type(artifact_id) is int and artifact_id > 0,
           "invalid artifact ID")
    _check(analyzed_source_sha is None or (
        isinstance(analyzed_source_sha, str)
        and bool(_SHA40.fullmatch(analyzed_source_sha))),
        "invalid analyzed source SHA")
    digest_re = re.compile(r"[0-9a-f]{64}\Z")
    for value in (expected_archive_digest, observed_archive_digest):
        _check(value is None or isinstance(value, str)
               and bool(digest_re.fullmatch(value)), "invalid SHA-256")
    _check(evidence_kind == "GITHUB_ACTIONS_ARTIFACT",
           "unsupported review evidence type")
    identity = {
        "repository": repository,
        "candidate_head_sha": candidate_head_sha,
        "analyzed_source_sha": analyzed_source_sha,
        "run_id": run_id,
        "artifact_id": artifact_id,
        "phase": phase,
        "category": category,
        "expected_archive_digest": expected_archive_digest,
        "observed_archive_digest": observed_archive_digest,
    }
    canonical = json.dumps(identity, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True)
    packet_id = "dea-review-" + sha256(canonical.encode("utf-8")).hexdigest()[:24]
    run_url = (
        "https://github.com/" + repository + "/actions/runs/" + str(run_id)
        if run_id is not None else None
    )
    artifact_url = (
        run_url + "/artifacts/" + str(artifact_id)
        if run_url is not None and artifact_id is not None else None
    )
    return {
        "schema_version": 1,
        "review_packet_id": packet_id,
        "status": "HUMAN_REVIEW_REQUIRED",
        "review_queue": "DEA_EVIDENCE_EXCEPTIONS",
        "reviewed": False,
        "identity": identity,
        "run_url": run_url,
        "artifact_url": artifact_url,
        "evidence_preservation": "DO_NOT_DELETE_OR_REWRITE",
        "safe_processing": "QUARANTINE_DO_NOT_EXECUTE_UNTRUSTED_BYTES",
        "human_options": [
            "REQUEST_FRESH_EVIDENCE",
            "INSPECT_ORIGINAL_ARTIFACT",
            "MARK_CONFIRMED_DEFECT",
            "RECORD_SCOPE_EXCEPTION_FOR_SEPARATE_APPROVAL",
        ],
        "automatic_fitness_hard_gate": "UNKNOWN",
        "pareto_eligible": False,
        "champion_promoted": False,
        "repository_mutation_authorized": False,
        "human_review_delivery": "NOT_CONFIGURED_BY_THIS_MODULE",
    }


def review_from_exception(
    exc: Exception, *, repository: str, candidate_head_sha: str,
    phase: str, run_id: int | None = None,
    artifact_id: int | None = None,
    analyzed_source_sha: str | None = None,
    expected_archive_digest: str | None = None,
    observed_archive_digest: str | None = None,
) -> dict[str, Any]:
    """Classify an error without publishing untrusted exception message.

    A forged candidate message cannot decide category or claim success.
    Unexpected failures are also reviewable, but never PASS.
    """
    name = type(exc).__name__
    if phase == "ARCHIVE_INTEGRITY":
        category = "INTEGRITY_MISMATCH"
    elif phase == "RUN_IDENTITY":
        category = "WRONG_IDENTITY"
    elif phase == "ARTIFACT_IDENTITY":
        category = "MISSING_EVIDENCE"
    elif phase == "PRODUCER_ATTESTATION":
        category = "PRODUCER_UNVERIFIED"
    elif phase == "SEMANTIC_ORACLE":
        category = "SEMANTIC_DIFFERENCE"
    elif phase == "ACQUISITION":
        category = "MISSING_EVIDENCE"
    else:
        category = "UNEXPECTED_VERIFICATION_ERROR"
    packet = make_review_packet(
        repository=repository, candidate_head_sha=candidate_head_sha,
        phase=phase, category=category,
        run_id=run_id, artifact_id=artifact_id,
        analyzed_source_sha=analyzed_source_sha,
        expected_archive_digest=expected_archive_digest,
        observed_archive_digest=observed_archive_digest,
    )
    packet["exception_class"] = name if name in {
        "ArtifactEvidenceError", "ReferenceOracleError", "EvidenceGateError",
        "AcquisitionError", "AttestationVerificationError",
    } else "UNCLASSIFIED_EXCEPTION"
    return packet


def handle_human_disposition(
    packet: dict[str, Any], *, disposition: str,
    reviewer_identity: str, review_reference: str,
) -> dict[str, Any]:
    """Record an externally decided disposition without overriding proof.

    Does not authenticate the reviewer; authorization is separately verified.
    No manual verdict can turn INVALID artifact bytes or UNKNOWN into PASS.
    """
    _check(isinstance(packet, dict)
           and packet.get("status") == "HUMAN_REVIEW_REQUIRED"
           and packet.get("pareto_eligible") is False,
           "not a reviewable DEA packet")
    _check(disposition in {
        "REQUEST_FRESH_EVIDENCE", "INSPECT_ORIGINAL_ARTIFACT",
        "MARK_CONFIRMED_DEFECT", "RECORD_SCOPE_EXCEPTION_FOR_SEPARATE_APPROVAL",
    }, "invalid disposition")
    _check(isinstance(reviewer_identity, str)
           and bool(reviewer_identity.strip())
           and len(reviewer_identity) <= 128,
           "reviewer identity required")
    _check(isinstance(review_reference, str)
           and bool(review_reference.strip())
           and len(review_reference) <= 1024,
           "review evidence reference required")
    return {
        "review_packet_id": packet["review_packet_id"],
        "status": "HUMAN_REVIEW_RECORDED_RECHECK_REQUIRED",
        "disposition": disposition,
        "reviewer_identity_claim": reviewer_identity,
        "review_reference": review_reference,
        "reviewer_authority": "NOT_ATTESTED_BY_THIS_MODULE",
        "fitness_hard_gate": "UNKNOWN",
        "recheck_required": True,
        "pareto_eligible": False,
        "repository_mutation_authorized": False,
    }
