"""DEA v0.2 evidence gate: read-only source/run/archive/Oracle correlation.

The caller obtains GitHub run+artifact-list metadata and archive BYTES by
independent authenticated readback, not by trusting candidate JSON.

Even if all bounded checks pass, producer-job attestation and trusted runner
execution are NOT proved. No automatic PASS/selection/merge is possible.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from chatgpt_operation.controller.dea_artifact_identity import (
    ArtifactEvidenceError, verify_artifact_zip, verify_github_artifact_listing,
)
from chatgpt_operation.controller.dea_reference_oracle import (
    ReferenceOracleError, assess_actions_run_readback, verify_candidate_from_git,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")


class EvidenceGateError(ValueError):
    """Unverifiable identity, content, semantic observation, or protocol."""


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise EvidenceGateError(message)


def check_evidence_bundle(
    *, source_repo_root: Path, github_run: dict[str, Any],
    github_artifact_listing: dict[str, Any], downloaded_archive_zip: bytes,
    expected_repository: str, expected_workflow_path: str,
    candidate_head_sha: str, analyzed_source_sha: str,
    oracle_revision_sha: str, measurement_set_sha: str,
    run_id: int, artifact_id: int, artifact_name: str,
) -> dict[str, Any]:
    """Independent readback comparison, but NO producer provenance claim.

    Two distinct SHAs are important: candidate_head_sha pins code executed in
    Actions, while analyzed_source_sha pins the documentation under analysis.
    They are not interchangeable.
    """
    for label, value in (
        ("candidate head", candidate_head_sha),
        ("analyzed source", analyzed_source_sha),
        ("oracle revision", oracle_revision_sha),
        ("measurement set", measurement_set_sha),
    ):
        _check(isinstance(value, str) and bool(_SHA.fullmatch(value)),
               "invalid exact " + label)
    try:
        run_check = assess_actions_run_readback(
            github_run, expected_repository=expected_repository,
            expected_head_sha=candidate_head_sha, expected_run_id=run_id,
            expected_workflow_path=expected_workflow_path,
        )
        _check(run_check["status"] == "RUN_METADATA_MATCH",
               "GitHub Actions run metadata mismatch")
        artifact = verify_github_artifact_listing(
            run=github_run, listing=github_artifact_listing,
            repository=expected_repository, expected_head_sha=candidate_head_sha,
            run_id=run_id, artifact_id=artifact_id, artifact_name=artifact_name,
        )
        archive = verify_artifact_zip(
            downloaded_archive_zip,
            expected_sha256=artifact["archive_digest_sha256"],
            expected_size_bytes=artifact["artifact_size_bytes"],
            run_id=run_id, artifact_id=artifact_id,
            candidate_head_sha=candidate_head_sha,
            analyzed_source_sha=analyzed_source_sha,
        )
        manifest = archive["manifest"]
        _check(manifest.get("oracle_revision_sha") == oracle_revision_sha
               and manifest.get("measurement_set_sha") == measurement_set_sha,
               "oracle or measurement protocol drift")
        semantics = verify_candidate_from_git(
            source_repo_root, analyzed_source_sha, archive["observations"]
        )
    except (ArtifactEvidenceError, ReferenceOracleError) as exc:
        raise EvidenceGateError(str(exc)) from exc
    # Never use a PASS verdict from candidate-authored validation-summary.json.
    # The independent computed result alone may detect a concrete failure.
    observed = semantics["status"]
    if observed == "FAIL":
        status = "FAILED_OBSERVATION"
        hard_gate = "FAIL"
    elif observed == "UNKNOWN":
        status = "UNKNOWN_SEMANTICS"
        hard_gate = "UNKNOWN"
    else:
        status = "BOUNDED_MATCH_PRODUCER_UNATTESTED"
        hard_gate = "UNKNOWN"
    return {
        "schema_version": 1,
        "status": status,
        "candidate_head_sha": candidate_head_sha,
        "analyzed_source_sha": analyzed_source_sha,
        "oracle_revision_sha": oracle_revision_sha,
        "measurement_set_sha": measurement_set_sha,
        "github_run_id": run_id, "github_artifact_id": artifact_id,
        "github_run_status": run_check["status"],
        "artifact_status": archive["status"],
        "artifact_zip_sha256": archive["archive_digest_sha256"],
        "trusted_source_corpus_sha256": semantics["trusted_corpus_digest_sha256"],
        "bounded_semantic_status": observed,
        "semantic_fitness_hard_gate": hard_gate,
        "candidate_reported_summary_ignored": True,
        "producer_job_attribution": "NOT_ATTESTED",
        "candidate_output_generation": "NOT_ATTESTED",
        "workflow_integrity": "NOT_ATTESTED",
        "runner_integrity": "NOT_ATTESTED",
        "source_remote_ownership": "NOT_ATTESTED",
        "external_consumers": "NOT_EVALUATED",
        "pareto_eligible": False,
        "champion": None,
        "repository_mutation_authorized": False,
    }


def to_fitness_semantic_receipt(
    evidence: dict[str, Any], *,
    analyzer_sha: str, profile_sha: str,
) -> dict[str, Any]:
    """Project bounded evidence into the existing v0.1 Fitness metadata schema.

    This cannot attest producer origin and therefore NEVER returns PASS.
    An observed mismatch can be FAIL; all other cases are UNKNOWN until a
    separate approved, independently authenticated producer exists.
    """
    _check(isinstance(evidence, dict), "missing verifier evidence")
    _check(all(isinstance(v, str) and bool(_SHA.fullmatch(v))
               for v in (analyzer_sha, profile_sha,
                         evidence.get("oracle_revision_sha"),
                         evidence.get("measurement_set_sha"),
                         evidence.get("candidate_head_sha"))),
           "invalid Fitness protocol identity")
    _check(type(evidence.get("github_run_id")) is int
           and evidence["github_run_id"] > 0
           and type(evidence.get("github_artifact_id")) is int
           and evidence["github_artifact_id"] > 0
           and isinstance(evidence.get("artifact_zip_sha256"), str)
           and bool(re.fullmatch(r"[0-9a-f]{64}", evidence["artifact_zip_sha256"])),
           "incomplete evidence reference")
    bounded = evidence.get("bounded_semantic_status")
    _check(bounded in ("FAIL", "UNKNOWN", "PASS_BOUNDED"),
           "unrecognized bounded semantic status")
    return {
        "observed_head_sha": evidence["candidate_head_sha"],
        "analyzer_sha": analyzer_sha,
        "profile_sha": profile_sha,
        "oracle_sha": evidence["oracle_revision_sha"],
        "measurement_set_sha": evidence["measurement_set_sha"],
        "evidence_ref": (
            "actions-run:" + str(evidence["github_run_id"])
            + "/artifact:" + str(evidence["github_artifact_id"])
            + "/sha256:" + evidence["artifact_zip_sha256"]
        ),
        "status": "FAIL" if bounded == "FAIL" else "UNKNOWN",
        "producer_attestation": "NOT_ATTESTED",
        "claim_scope": "BOUNDED_READBACK_NO_AUTOMATIC_PROMOTION",
    }
