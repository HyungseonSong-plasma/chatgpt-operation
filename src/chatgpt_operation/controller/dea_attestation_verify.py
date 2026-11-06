"""GitHub-CLI verified Sigstore/SLSA attestation for DEA signed payload bytes.

Only GitHub CLI attestation verify can establish cryptographic signer identity;
a candidate-authored JSON verified field is never trusted. The signed
subject is the *inner* DEA payload zip, not GitHub's outer download archive.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_WORKFLOW = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/[A-Za-z0-9_.-]+\.(?:yml|yaml)\Z")
_MAX_PAYLOAD = 20_000_000
_MAX_STDOUT = 5_000_000


class AttestationVerificationError(ValueError):
    pass


def verify_sigstore_payload(
    payload: bytes, *, repository: str, signer_workflow: str,
    signer_revision_sha: str, source_revision_sha: str,
) -> dict[str, Any]:
    """Perform real online cryptographic verification with pinned identities.

    Success is specifically bounded: source + signer + subject integrity.
    It is NOT a validated semantic oracle or specific Actions job receipt.
    """
    if not isinstance(payload, bytes) or not 0 < len(payload) <= _MAX_PAYLOAD:
        raise AttestationVerificationError("invalid signed subject size")
    if not isinstance(repository, str) or not _REPO.fullmatch(repository):
        raise AttestationVerificationError("invalid attestation repository")
    if not isinstance(signer_workflow, str) or not _WORKFLOW.fullmatch(signer_workflow):
        raise AttestationVerificationError("invalid signer workflow")
    if not all(isinstance(x, str) and _SHA40.fullmatch(x)
               for x in (signer_revision_sha, source_revision_sha)):
        raise AttestationVerificationError("exact source and signer SHAs required")
    digest = sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory(prefix="dea-sigstore-") as directory:
        path = Path(directory) / "dea-evidence.zip"
        path.write_bytes(payload)
        argv = [
            "gh", "attestation", "verify", str(path),
            "--repo", repository,
            "--signer-workflow", signer_workflow,
            "--signer-digest", signer_revision_sha,
            "--source-digest", source_revision_sha,
            "--deny-self-hosted-runners",
            "--predicate-type", "https://slsa.dev/provenance/v1",
            "--format", "json",
        ]
        try:
            result = subprocess.run(
                argv, capture_output=True, check=False, timeout=90,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AttestationVerificationError("trusted gh verification unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > _MAX_STDOUT:
        raise AttestationVerificationError("GitHub attestation verification failed")
    try:
        rows = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise AttestationVerificationError("malformed verified attestation") from exc
    if not isinstance(rows, list) or not rows:
        raise AttestationVerificationError("no cryptographically verified attestations")
    accepted = False
    for item in rows:
        if not isinstance(item, dict):
            continue
        result = item.get("verificationResult")
        if not isinstance(result, dict):
            continue
        statement = result.get("statement")
        signature = result.get("signature")
        if not isinstance(statement, dict) or not isinstance(signature, dict):
            continue
        cert = signature.get("certificate")
        if not isinstance(cert, dict):
            continue
        if statement.get("predicateType") != "https://slsa.dev/provenance/v1":
            continue
        subjects = statement.get("subject", [])
        if not isinstance(subjects, list):
            continue
        if any(isinstance(x, dict)
               and isinstance(x.get("digest"), dict)
               and x["digest"].get("sha256") == digest for x in subjects):
            accepted = True
            break
    if not accepted:
        raise AttestationVerificationError("attested subject digest mismatches bytes")
    return {
        "status": "CRYPTOGRAPHIC_SUBJECT_SIGNER_VERIFIED",
        "subject_sha256": digest,
        "repository": repository,
        "signer_workflow": signer_workflow,
        "signer_revision_sha": signer_revision_sha,
        "source_revision_sha": source_revision_sha,
        "verified_via": "GH_ATTESTATION_VERIFY_SIGSTORE",
        "attested_run_id": "NOT_ATTESTED_BY_THIS_MODULE",
        "producer_job_attribution": "NOT_ATTESTED_BY_THIS_MODULE",
        "reference_semantics": "NOT_EVALUATED",
        "fitness_hard_gate": "UNKNOWN",
        "pareto_eligible": False,
        "repository_mutation_authorized": False,
    }
