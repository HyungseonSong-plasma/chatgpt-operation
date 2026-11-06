"""Fail-closed tests for GitHub Actions artifact metadata and archive identity."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from chatgpt_operation.controller.dea_artifact_identity import (
    ArtifactEvidenceError, verify_artifact_zip, verify_github_artifact_listing,
)

HEAD = "a" * 40
SOURCE = "b" * 40
REPO = "HyungseonSong-plasma/codeQA"
RUN_ID = 731
ARTIFACT_ID = 812
NAME = "dea-candidate-a"


def payload():
    files = {
        "observations.json": {"source_revision": SOURCE, "records": []},
        "fitness-metrics.json": {"time_ms": 15},
        "validation-summary.json": {"decision": "PROVISIONAL"},
    }
    hashes = {
        name: sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()
        for name, contents in files.items()
    }
    files["execution-manifest.json"] = {
        "schema_version": 1, "run_id": RUN_ID, "artifact_id": ARTIFACT_ID,
        "candidate_head_sha": HEAD, "analyzed_source_sha": SOURCE,
        "file_sha256": hashes,
    }
    b = BytesIO()
    with ZipFile(b, "w", compression=ZIP_DEFLATED) as z:
        for name, obj in sorted(files.items()):
            z.writestr(name, json.dumps(obj, sort_keys=True))
    return b.getvalue()


def github_fixture(archive):
    run = {
        "repository": {"id": 14, "full_name": REPO},
        "id": RUN_ID, "head_sha": HEAD, "status": "completed",
        "conclusion": "success",
    }
    listing = {"total_count": 1, "artifacts": [{
        "id": ARTIFACT_ID, "name": NAME, "expired": False,
        "size_in_bytes": len(archive),
        "digest": "sha256:" + sha256(archive).hexdigest(),
        "workflow_run": {
            "id": RUN_ID, "head_sha": HEAD, "repository_id": 14
        },
    }]}
    return run, listing


def check_metadata(run, listing):
    return verify_github_artifact_listing(
        run=run, listing=listing, repository=REPO, expected_head_sha=HEAD,
        run_id=RUN_ID, artifact_id=ARTIFACT_ID, artifact_name=NAME,
    )


def check_archive(data):
    return verify_artifact_zip(
        data, expected_sha256=sha256(data).hexdigest(),
        expected_size_bytes=len(data), run_id=RUN_ID,
        artifact_id=ARTIFACT_ID, candidate_head_sha=HEAD,
        analyzed_source_sha=SOURCE,
    )


class ArtifactIdentityTests(unittest.TestCase):
    def test_valid_identity_and_contents_are_not_job_attestation(self):
        b = payload()
        run, listing = github_fixture(b)
        result = check_metadata(run, listing)
        self.assertEqual(result["status"], "METADATA_IDENTITY_MATCH")
        self.assertEqual(result["producer_job_attribution"], "NOT_ATTESTED")
        content = check_archive(b)
        self.assertEqual(content["status"], "ARCHIVE_CONTENT_MATCH")
        self.assertEqual(content["producer_job_attribution"], "NOT_ATTESTED")
        self.assertFalse(content["repository_mutation_authorized"])

    def test_wrong_run_identity_and_other_repository_fail(self):
        archive = payload()
        run, listing = github_fixture(archive)
        for field, value in (("head_sha", "f" * 40), ("id", 732),
                             ("status", "queued"), ("conclusion", "failure")):
            modified = deepcopy(run)
            modified[field] = value
            with self.subTest(field=field), self.assertRaises(ArtifactEvidenceError):
                check_metadata(modified, listing)
        modified = deepcopy(run)
        modified["repository"]["full_name"] = "someone/else"
        with self.assertRaises(ArtifactEvidenceError):
            check_metadata(modified, listing)

    def test_incomplete_listing_and_duplicate_ids_rejected(self):
        archive = payload()
        run, listing = github_fixture(archive)
        listing["total_count"] = 2
        with self.assertRaises(ArtifactEvidenceError):
            check_metadata(run, listing)
        listing = github_fixture(archive)[1]
        listing["artifacts"].append(deepcopy(listing["artifacts"][0]))
        listing["total_count"] = 2
        with self.assertRaises(ArtifactEvidenceError):
            check_metadata(run, listing)

    def test_artifact_digest_and_expiration_fail_closed(self):
        archive = payload()
        run, listing = github_fixture(archive)
        for field, value in (
            ("digest", None), ("digest", "sha256:" + "c" * 64),
            ("expired", True), ("size_in_bytes", 0),
        ):
            altered = deepcopy(listing)
            altered["artifacts"][0][field] = value
            if field == "digest" and value and len(value) == 71:
                # Correctly-shaped but forged digest must fail when checked
                # against actual archive bytes.
                metadata = check_metadata(run, altered)
                with self.assertRaises(ArtifactEvidenceError):
                    verify_artifact_zip(
                        archive, expected_sha256=metadata["archive_digest_sha256"],
                        expected_size_bytes=len(archive), run_id=RUN_ID,
                        artifact_id=ARTIFACT_ID, candidate_head_sha=HEAD,
                        analyzed_source_sha=SOURCE,
                    )
            else:
                with self.assertRaises(ArtifactEvidenceError):
                    check_metadata(run, altered)

    def test_mismatched_artifact_workflow_and_repository_id(self):
        archive = payload()
        run, listing = github_fixture(archive)
        for field, bad in (("id", 999), ("repository_id", 999),
                           ("head_sha", "f" * 40)):
            altered = deepcopy(listing)
            altered["artifacts"][0]["workflow_run"][field] = bad
            with self.subTest(field=field), self.assertRaises(ArtifactEvidenceError):
                check_metadata(run, altered)

    def test_digest_byte_count_and_manifest_identity(self):
        archive = payload()
        with self.assertRaises(ArtifactEvidenceError):
            verify_artifact_zip(
                archive, expected_sha256="c" * 64, expected_size_bytes=len(archive),
                run_id=RUN_ID, artifact_id=ARTIFACT_ID,
                candidate_head_sha=HEAD, analyzed_source_sha=SOURCE,
            )
        with self.assertRaises(ArtifactEvidenceError):
            verify_artifact_zip(
                archive, expected_sha256=sha256(archive).hexdigest(),
                expected_size_bytes=len(archive) + 1,
                run_id=RUN_ID, artifact_id=ARTIFACT_ID,
                candidate_head_sha=HEAD, analyzed_source_sha=SOURCE,
            )
        with self.assertRaises(ArtifactEvidenceError):
            verify_artifact_zip(
                archive, expected_sha256=sha256(archive).hexdigest(),
                expected_size_bytes=len(archive), run_id=RUN_ID + 1,
                artifact_id=ARTIFACT_ID,
                candidate_head_sha=HEAD, analyzed_source_sha=SOURCE,
            )

    def test_reject_path_traversal_and_extra_member(self):
        archive = payload()
        for extra in ("../traversal.txt", "unexpected.json"):
            b = BytesIO()
            with ZipFile(BytesIO(archive)) as z, ZipFile(b, "w") as out:
                for info in z.infolist():
                    out.writestr(info.filename, z.read(info.filename))
                out.writestr(extra, "attacker")
            with self.subTest(extra=extra), self.assertRaises(ArtifactEvidenceError):
                check_archive(b.getvalue())

    def test_reject_internal_file_hash_disagreement(self):
        archive = payload()
        b = BytesIO()
        with ZipFile(BytesIO(archive)) as z, ZipFile(b, "w") as out:
            for info in z.infolist():
                data = z.read(info.filename)
                if info.filename == "observations.json":
                    data = b'{"source_revision":"forged","records":[]}'
                out.writestr(info.filename, data)
        with self.assertRaisesRegex(ArtifactEvidenceError, "file SHA-256"):
            check_archive(b.getvalue())

    def test_unparseable_zip_and_json(self):
        with self.assertRaises(ArtifactEvidenceError):
            check_archive(b"not a zip")


if __name__ == "__main__":
    unittest.main()
