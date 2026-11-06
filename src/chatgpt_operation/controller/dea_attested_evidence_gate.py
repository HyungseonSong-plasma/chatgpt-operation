"""DEA v2 signed evidence: independent GitHub readback, Sigstore and Oracle.

No automatic candidate promotion: GitHub Actions run/job linkage still needs
a separately authorized producer workflow and verified execution identity.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from chatgpt_operation.controller.dea_artifact_identity import (
    ArtifactEvidenceError, verify_github_artifact_listing,
)
from chatgpt_operation.controller.dea_attested_payload import (
    PayloadContractError, inspect_payload, unwrap_github_artifact_zip,
)
from chatgpt_operation.controller.dea_attestation_verify import (
    AttestationVerificationError, verify_sigstore_payload,
)
from chatgpt_operation.controller.dea_reference_oracle import (
    ReferenceOracleError, assess_actions_run_readback,
    verify_candidate_from_git,
)
from chatgpt_operation.controller.dea_review_routing import review_from_exception


class SignedEvidenceError(ValueError):
    pass


def verify_signed_evidence(
    *, source_repo_root: Path,
    github_run: dict[str, Any], github_artifact_listing: dict[str, Any],
    downloaded_archive_zip: bytes,
    expected_repository: str, expected_workflow_path: str,
    candidate_head_sha: str, analyzed_source_sha: str,
    oracle_revision_sha: str, measurement_set_sha: str,
    run_id: int, artifact_id: int, artifact_name: str,
    signer_workflow: str, signer_revision_sha: str,
) -> dict[str, Any]:
    """Verify independent subject/signature/source in the bounded v2 format.

    Caller-fetched GitHub data must come from an authenticated trusted reader.
    Does not treat synthetic archives as signed or claim user-level approval.
    """
    run_readback = assess_actions_run_readback(
        github_run, expected_repository=expected_repository,
        expected_head_sha=candidate_head_sha, expected_run_id=run_id,
        expected_workflow_path=expected_workflow_path,
    )
    if run_readback["status"] != "RUN_METADATA_MATCH":
        raise SignedEvidenceError("run metadata identity mismatch")
    identity = verify_github_artifact_listing(
        run=github_run, listing=github_artifact_listing,
        repository=expected_repository,
        expected_head_sha=candidate_head_sha,
        run_id=run_id, artifact_id=artifact_id, artifact_name=artifact_name,
    )
    subject = unwrap_github_artifact_zip(
        downloaded_archive_zip,
        expected_outer_digest=identity["archive_digest_sha256"],
        expected_outer_size=identity["artifact_size_bytes"],
    )
    signed = verify_sigstore_payload(
        subject, repository=expected_repository,
        signer_workflow=signer_workflow,
        signer_revision_sha=signer_revision_sha,
        source_revision_sha=candidate_head_sha,
    )
    content = inspect_payload(
        subject, repository=expected_repository, run_id=run_id,
        candidate_head_sha=candidate_head_sha,
        analyzed_source_sha=analyzed_source_sha,
        oracle_revision_sha=oracle_revision_sha,
        measurement_set_sha=measurement_set_sha,
    )
    semantics = verify_candidate_from_git(
        source_repo_root, analyzed_source_sha, content["observations"],
    )
    observed = semantics["status"]
    # Independently observed divergence is a FAIL. Otherwise we still need
    # GitHub run/job receipt and independent consumer coverage before PASS.
    fitness_gate = "FAIL" if observed == "FAIL" else "UNKNOWN"
    return {
        "schema_version": 2,
        "status": ("FAILED_OBSERVATION_REVIEW_REQUIRED" if observed == "FAIL"
                   else "SIGNED_EVIDENCE_BOUNDED_REVIEW_REQUIRED"),
        "run_identity": run_readback["status"],
        "artifact_identity": identity["status"],
        "signed_subject_identity": signed["status"],
        "payload_identity": content["status"],
        "candidate_head_sha": candidate_head_sha,
        "analyzed_source_sha": analyzed_source_sha,
        "run_id": run_id, "artifact_id": artifact_id,
        "outer_artifact_sha256": identity["archive_digest_sha256"],
        "signed_subject_sha256": content["payload_sha256"],
        "bounded_semantics": observed,
        "fitness_hard_gate": fitness_gate,
        "producer_signer_identity": signed["signer_workflow"],
        "producer_job_id": "NOT_ATTESTED_BY_THIS_MODULE",
        "run_to_attestation_binding": "NOT_ATTESTED_BY_THIS_MODULE",
        "known_external_consumers": "NOT_EVALUATED",
        "review_required": True,
        "pareto_eligible": False, "champion": None,
        "repository_mutation_authorized": False,
    }


def verify_or_route_review(
    *, repository: str, candidate_head_sha: str,
    analyzed_source_sha: str, run_id: int, artifact_id: int,
    **kwargs: Any,
) -> dict[str, Any]:
    """Never drop failed evidence; emit review packet for failed verification.

    This method deliberately preserves a non-PASS result. An authorized
    delivery service must separately submit the review packet to humans.
    """
    try:
        return verify_signed_evidence(
            expected_repository=repository,
            candidate_head_sha=candidate_head_sha,
            analyzed_source_sha=analyzed_source_sha,
            run_id=run_id, artifact_id=artifact_id, **kwargs,
        )
    except (SignedEvidenceError, ArtifactEvidenceError,
            PayloadContractError, AttestationVerificationError,
            ReferenceOracleError) as exc:
        return review_from_exception(
            exc, repository=repository, candidate_head_sha=candidate_head_sha,
            analyzed_source_sha=analyzed_source_sha,
            run_id=run_id, artifact_id=artifact_id,
            phase=("PRODUCER_ATTESTATION"
                   if isinstance(exc, AttestationVerificationError)
                   else "ARCHIVE_INTEGRITY"
                   if isinstance(exc, (ArtifactEvidenceError, PayloadContractError))
                   else "SEMANTIC_ORACLE"
                   if isinstance(exc, ReferenceOracleError)
                   else "RUN_IDENTITY"),
        )
