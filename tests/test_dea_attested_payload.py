"""Signed DEA v2 payload and GitHub outer artifact wrapper negative controls."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from unittest.mock import patch
import subprocess
import unittest
from zipfile import ZipFile

from chatgpt_operation.controller.dea_attested_payload import (
    PayloadContractError, build_payload, inspect_payload,
    unwrap_github_artifact_zip,
)
from chatgpt_operation.controller.dea_attestation_verify import (
    AttestationVerificationError, verify_sigstore_payload,
)

REPO = "HyungseonSong-plasma/codeQA"
HEAD, SOURCE, ORACLE, MEAS, SIGNER = (
    "a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40
)
SIGNER_WORKFLOW = (
    "HyungseonSong-plasma/chatgpt-operation/"
    ".github/workflows/dea-evidence-producer.yml"
)


def signed_payload(**overrides):
    args = {
        "repository": REPO, "run_id": 123,
        "candidate_head_sha": HEAD, "analyzed_source_sha": SOURCE,
        "oracle_revision_sha": ORACLE, "measurement_set_sha": MEAS,
        "observations": {"source_revision": SOURCE, "records": []},
        "metrics": {"wall_time_ms": 2.5},
        "summary": {"reported": "PASS", "champion": True},
    }
    args.update(overrides)
    return build_payload(**args)


def inspect(data):
    return inspect_payload(
        data, repository=REPO, run_id=123,
        candidate_head_sha=HEAD, analyzed_source_sha=SOURCE,
        oracle_revision_sha=ORACLE, measurement_set_sha=MEAS,
    )


def outer(data):
    b = BytesIO()
    with ZipFile(b, "w") as z:
        z.writestr("dea-evidence.zip", data)
    return b.getvalue()


class AttestedPayloadTests(unittest.TestCase):
    def test_determinism_and_no_circular_artifact_id(self):
        a, b = signed_payload(), signed_payload()
        self.assertEqual(a, b)
        summary = inspect(a)
        self.assertEqual(summary["status"], "SIGNED_SUBJECT_CONTENT_VALID")
        self.assertEqual(summary["manifest"]["schema_version"], 2)
        self.assertNotIn("artifact_id", summary["manifest"])
        self.assertEqual(summary["manifest"]["artifact_id_binding"],
                         "POST_UPLOAD_GITHUB_API")
        self.assertIsNone(summary["artifact_id"])
        self.assertFalse(summary["automatic_fitness_pass"])

    def test_github_outer_archive_and_inner_subject_distinguished(self):
        payload = signed_payload()
        wrapper = outer(payload)
        self.assertNotEqual(sha256(payload).hexdigest(),
                            sha256(wrapper).hexdigest())
        extracted = unwrap_github_artifact_zip(
            wrapper, expected_outer_digest=sha256(wrapper).hexdigest(),
            expected_outer_size=len(wrapper),
        )
        self.assertEqual(extracted, payload)
        self.assertEqual(inspect(extracted)["payload_sha256"],
                         sha256(payload).hexdigest())

    def test_wrong_wrapper_digest_or_member_rejected(self):
        data = outer(signed_payload())
        with self.assertRaises(PayloadContractError):
            unwrap_github_artifact_zip(
                data, expected_outer_digest="0" * 64,
                expected_outer_size=len(data),
            )
        with self.assertRaises(PayloadContractError):
            unwrap_github_artifact_zip(
                data, expected_outer_digest=sha256(data).hexdigest(),
                expected_outer_size=len(data) + 1,
            )
        b = BytesIO()
        with ZipFile(b, "w") as z:
            z.writestr("../unsafe", signed_payload())
        with self.assertRaises(PayloadContractError):
            unwrap_github_artifact_zip(
                b.getvalue(), expected_outer_digest=sha256(b.getvalue()).hexdigest(),
                expected_outer_size=len(b.getvalue()),
            )

    def test_source_and_run_drift_are_not_relabelled(self):
        payload = signed_payload()
        for kwargs in (
            {"run_id": 124},
            {"candidate_head_sha": "f" * 40},
            {"analyzed_source_sha": "f" * 40},
            {"oracle_revision_sha": "f" * 40},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PayloadContractError):
                inspect_payload(
                    payload, repository=REPO, run_id=kwargs.get("run_id", 123),
                    candidate_head_sha=kwargs.get("candidate_head_sha", HEAD),
                    analyzed_source_sha=kwargs.get("analyzed_source_sha", SOURCE),
                    oracle_revision_sha=kwargs.get("oracle_revision_sha", ORACLE),
                    measurement_set_sha=MEAS,
                )

    def test_nonfinite_and_invalid_sources_rejected(self):
        with self.assertRaises(PayloadContractError):
            signed_payload(metrics={"time_ms": float("nan")})
        with self.assertRaises(PayloadContractError):
            signed_payload(observations={"source_revision": "f" * 40})


class AttestationVerificationTests(unittest.TestCase):
    def fake_result(self, payload, *, digest=None, good=True):
        x = digest or sha256(payload).hexdigest()
        return subprocess.CompletedProcess(
            args=["gh"], returncode=0 if good else 1,
            stdout=json.dumps([{
                "verificationResult": {
                    "statement": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [{"name": "dea-evidence.zip",
                                     "digest": {"sha256": x}}],
                    },
                    "signature": {"certificate": {"sourceRepository": REPO}},
                },
            }]).encode(),
            stderr=b"",
        )

    def test_cryptographic_verification_uses_precise_cli_flags(self):
        payload = signed_payload()
        with patch("subprocess.run", return_value=self.fake_result(payload)) as p:
            receipt = verify_sigstore_payload(
                payload, repository=REPO, signer_workflow=SIGNER_WORKFLOW,
                signer_revision_sha=SIGNER, source_revision_sha=HEAD,
            )
        argv = p.call_args.args[0]
        self.assertEqual(argv[:3], ["gh", "attestation", "verify"])
        self.assertEqual(argv[argv.index("--signer-workflow") + 1],
                         SIGNER_WORKFLOW)
        self.assertEqual(argv[argv.index("--signer-digest") + 1], SIGNER)
        self.assertEqual(argv[argv.index("--source-digest") + 1], HEAD)
        self.assertIn("--deny-self-hosted-runners", argv)
        self.assertEqual(receipt["status"], "CRYPTOGRAPHIC_SUBJECT_SIGNER_VERIFIED")
        self.assertEqual(receipt["producer_job_attribution"],
                         "NOT_ATTESTED_BY_THIS_MODULE")
        self.assertFalse(receipt["pareto_eligible"])

    def test_wrong_subject_or_unverified_signature_fail(self):
        payload = signed_payload()
        for result in (
            self.fake_result(payload, digest="0" * 64),
            self.fake_result(payload, good=False),
        ):
            with patch("subprocess.run", return_value=result):
                with self.assertRaises(AttestationVerificationError):
                    verify_sigstore_payload(
                        payload, repository=REPO, signer_workflow=SIGNER_WORKFLOW,
                        signer_revision_sha=SIGNER, source_revision_sha=HEAD,
                    )

    def test_forged_signer_identity_and_source_are_not_accepted(self):
        payload = signed_payload()
        with patch("subprocess.run") as mock:
            with self.assertRaises(AttestationVerificationError):
                verify_sigstore_payload(
                    payload, repository=REPO,
                    signer_workflow="owner/repo/../../evil.yml",
                    signer_revision_sha=SIGNER, source_revision_sha=HEAD,
                )
            mock.assert_not_called()
        with patch("subprocess.run") as mock:
            with self.assertRaises(AttestationVerificationError):
                verify_sigstore_payload(
                    payload, repository=REPO,
                    signer_workflow=SIGNER_WORKFLOW,
                    signer_revision_sha="not-sha", source_revision_sha=HEAD,
                )
            mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
