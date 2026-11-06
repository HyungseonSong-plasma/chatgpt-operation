"""Synthetic v2 official attestation integration: no live workflows dispatched."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from chatgpt_operation.controller.dea_attested_payload import build_payload
from chatgpt_operation.controller.dea_attestation_verify import (
    AttestationVerificationError,
)
from chatgpt_operation.controller.dea_attested_evidence_gate import (
    verify_or_route_review,
)
from chatgpt_operation.controller.dea_payload_producer import main
from chatgpt_operation.controller.dea_reference_oracle import scan_git_snapshot

REPO = "HyungseonSong-plasma/codeQA"
HEAD = "a" * 40
ORACLE = "b" * 40
MEASUREMENT = "c" * 40
SIGNER = "d" * 40
SIGNER_PATH = (
    "HyungseonSong-plasma/chatgpt-operation/"
    ".github/workflows/dea-evidence-producer.yml"
)
WORKFLOW = ".github/workflows/dea-candidate-verify.yml"


def git(root, *args):
    return subprocess.check_output(
        ["git", *args], cwd=root, stderr=subprocess.DEVNULL
    ).decode().strip()


def setup_git(root):
    git(root, "init", "-q")
    git(root, "config", "user.name", "DEA")
    git(root, "config", "user.email", "dea@example.invalid")
    a = root / "docs/a.md"
    a.parent.mkdir(parents=True)
    a.write_text("[A](b.md#valid)\n")
    (root / "docs/b.md").write_text("# Valid\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return git(root, "rev-parse", "HEAD")


def fixture(root, sha):
    observations = scan_git_snapshot(root, sha)
    payload = build_payload(
        repository=REPO, run_id=123,
        candidate_head_sha=HEAD, analyzed_source_sha=sha,
        oracle_revision_sha=ORACLE, measurement_set_sha=MEASUREMENT,
        observations=observations,
        metrics={"wall_time_ms": 1}, summary={"status": "PASS"},
    )
    wrapper_buffer = BytesIO()
    with ZipFile(wrapper_buffer, "w") as z:
        z.writestr("dea-evidence.zip", payload)
    wrapper = wrapper_buffer.getvalue()
    run = {
        "id": 123, "head_sha": HEAD, "path": WORKFLOW,
        "status": "completed", "conclusion": "success",
        "repository": {"id": 99, "full_name": REPO},
    }
    listing = {
        "total_count": 1,
        "artifacts": [{
            "id": 456, "name": "dea-A",
            "size_in_bytes": len(wrapper),
            "digest": "sha256:" + sha256(wrapper).hexdigest(),
            "expired": False,
            "workflow_run": {
                "id": 123, "head_sha": HEAD, "repository_id": 99,
            },
        }],
    }
    args = {
        "repository": REPO,
        "source_repo_root": root, "github_run": run,
        "github_artifact_listing": listing,
        "downloaded_archive_zip": wrapper,
        "expected_workflow_path": WORKFLOW,
        "candidate_head_sha": HEAD, "analyzed_source_sha": sha,
        "oracle_revision_sha": ORACLE, "measurement_set_sha": MEASUREMENT,
        "run_id": 123, "artifact_id": 456,
        "artifact_name": "dea-A",
        "signer_workflow": SIGNER_PATH, "signer_revision_sha": SIGNER,
    }
    return args


class SignedGateTests(unittest.TestCase):
    def test_signed_bundle_still_requires_human_review_and_run_job_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sha = setup_git(root)
            args = fixture(root, sha)
            from chatgpt_operation.controller.dea_attested_evidence_gate import (
                verify_sigstore_payload,
            )
            with patch(
                "chatgpt_operation.controller.dea_attested_evidence_gate."
                "verify_sigstore_payload",
                return_value={"status": "CRYPTOGRAPHIC_SUBJECT_SIGNER_VERIFIED",
                              "signer_workflow": SIGNER_PATH},
            ):
                result = verify_or_route_review(**args)
            self.assertEqual(result["signed_subject_identity"],
                             "CRYPTOGRAPHIC_SUBJECT_SIGNER_VERIFIED")
            self.assertEqual(result["bounded_semantics"], "PASS_BOUNDED")
            self.assertEqual(result["fitness_hard_gate"], "UNKNOWN")
            self.assertTrue(result["review_required"])
            self.assertEqual(result["producer_job_id"], "NOT_ATTESTED_BY_THIS_MODULE")
            self.assertFalse(result["pareto_eligible"])

    def test_unverified_attestation_routes_to_review_not_drops_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sha = setup_git(root)
            args = fixture(root, sha)
            with patch(
                "chatgpt_operation.controller.dea_attested_evidence_gate."
                "verify_sigstore_payload",
                side_effect=AttestationVerificationError("invalid signature"),
            ):
                result = verify_or_route_review(**args)
            self.assertEqual(result["status"], "HUMAN_REVIEW_REQUIRED")
            self.assertEqual(result["identity"]["phase"],
                             "PRODUCER_ATTESTATION")
            self.assertEqual(result["identity"]["artifact_id"], 456)
            self.assertFalse(result["pareto_eligible"])

    def test_wrong_digest_routes_to_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sha = setup_git(root)
            args = fixture(root, sha)
            args["github_artifact_listing"]["artifacts"][0]["digest"] = (
                "sha256:" + "f" * 64
            )
            result = verify_or_route_review(**args)
            self.assertEqual(result["status"], "HUMAN_REVIEW_REQUIRED")
            self.assertEqual(result["identity"]["phase"], "ARCHIVE_INTEGRITY")
            self.assertFalse(result["repository_mutation_authorized"])

    def test_wrong_actions_run_routes_to_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sha = setup_git(root)
            args = fixture(root, sha)
            args["github_run"]["head_sha"] = "f" * 40
            result = verify_or_route_review(**args)
            self.assertEqual(result["status"], "HUMAN_REVIEW_REQUIRED")
            self.assertEqual(result["identity"]["phase"], "RUN_IDENTITY")


class ProducerCLITests(unittest.TestCase):
    def test_local_producer_writes_only_signed_subject_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = "e" * 40
            for name, value in (
                ("observations", {"source_revision": src, "records": []}),
                ("metrics", {"wall_time_ms": 15}),
                ("summary", {"status": "PASS"}),
            ):
                (root / (name + ".json")).write_text(json.dumps(value))
            argv = [
                "--repository", REPO, "--run-id", "123",
                "--candidate-head", HEAD,
                "--analyzed-source-sha", src,
                "--oracle-revision-sha", ORACLE,
                "--measurement-set-sha", MEASUREMENT,
                "--observations-json", str(root / "observations.json"),
                "--metrics-json", str(root / "metrics.json"),
                "--summary-json", str(root / "summary.json"),
                "--output", str(root / "dea-evidence.zip"),
            ]
            with patch("builtins.print"):
                self.assertEqual(main(argv), 0)
                self.assertTrue((root / "dea-evidence.zip").is_file())
                self.assertEqual(main(argv), 2)
            self.assertEqual(list(root.glob("*.zip")), [root / "dea-evidence.zip"])


if __name__ == "__main__":
    unittest.main()
