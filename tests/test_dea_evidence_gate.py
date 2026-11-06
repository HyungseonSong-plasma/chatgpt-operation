"""End-to-end synthetic Git/Actions/artifact/Oracle readback tests.

No GitHub writes or real candidate artifact are assumed by these fixtures.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from chatgpt_operation.controller.dea_evidence_gate import (
    EvidenceGateError, check_evidence_bundle, to_fitness_semantic_receipt,
)
from chatgpt_operation.controller.dea_reference_oracle import scan_git_snapshot

CANDIDATE_HEAD = "a" * 40
ORACLE_REV = "b" * 40
MEASUREMENTS = "c" * 40
REPO = "HyungseonSong-plasma/codeQA"
WORKFLOW = ".github/workflows/dea-candidate-verify.yml"
RUN_ID = 1411
ARTIFACT_ID = 9191


def make_run():
    return {
        "id": RUN_ID, "head_sha": CANDIDATE_HEAD, "path": WORKFLOW,
        "status": "completed", "conclusion": "success",
        "repository": {"id": 15, "full_name": REPO},
    }


def make_archive(*, source_sha, observations,
                 summary=None, manifest_override=None):
    files = {
        "observations.json": observations,
        "fitness-metrics.json": {"reported_wall_time_ms": 0.01},
        "validation-summary.json": summary or {"self_reported": "PASS"},
    }
    hashes = {
        name: sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        for name, value in files.items()
    }
    manifest = {
        "schema_version": 1, "run_id": RUN_ID, "artifact_id": ARTIFACT_ID,
        "candidate_head_sha": CANDIDATE_HEAD, "analyzed_source_sha": source_sha,
        "oracle_revision_sha": ORACLE_REV,
        "measurement_set_sha": MEASUREMENTS,
        "file_sha256": hashes,
    }
    manifest.update(manifest_override or {})
    files["execution-manifest.json"] = manifest
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as z:
        for name, value in sorted(files.items()):
            z.writestr(name, json.dumps(value, sort_keys=True))
    return output.getvalue()


def make_listing(data, source_sha):
    del source_sha
    return {
        "total_count": 1,
        "artifacts": [{
            "id": ARTIFACT_ID, "name": "dea-pilot-A",
            "size_in_bytes": len(data), "expired": False,
            "digest": "sha256:" + sha256(data).hexdigest(),
            "workflow_run": {
                "id": RUN_ID, "head_sha": CANDIDATE_HEAD,
                "repository_id": 15,
            },
        }],
    }


def git(root, *cmd):
    return subprocess.check_output(
        ["git", *cmd], cwd=root, stderr=subprocess.DEVNULL
    ).decode("utf-8").strip()


def init_source(root, *, unknown=False):
    git(root, "init", "-q")
    git(root, "config", "user.name", "DEA Test")
    git(root, "config", "user.email", "dea-test@example.invalid")
    document = root / "docs/a.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(
        "[Link](b.md#missing)\n" if unknown else "[Link](b.md#valid)\n"
    )
    (root / "docs/b.md").write_text("# Valid\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "source")
    return git(root, "rev-parse", "HEAD")


class EvidenceGateTests(unittest.TestCase):
    def compare(self, root, source_sha, *, observations=None,
                run=None, listing=None, manifest_override=None,
                summary=None, archive=None):
        if observations is None:
            observations = scan_git_snapshot(root, source_sha)
        data = archive if archive is not None else make_archive(
            source_sha=source_sha, observations=observations,
            manifest_override=manifest_override, summary=summary,
        )
        listing = make_listing(data, source_sha) if listing is None else listing
        return check_evidence_bundle(
            source_repo_root=root, github_run=make_run() if run is None else run,
            github_artifact_listing=listing, downloaded_archive_zip=data,
            expected_repository=REPO, expected_workflow_path=WORKFLOW,
            candidate_head_sha=CANDIDATE_HEAD, analyzed_source_sha=source_sha,
            oracle_revision_sha=ORACLE_REV, measurement_set_sha=MEASUREMENTS,
            run_id=RUN_ID, artifact_id=ARTIFACT_ID, artifact_name="dea-pilot-A",
        )

    def test_valid_bundle_remains_unqualified_without_producer_attestation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            before = git(root, "status", "--porcelain")
            result = self.compare(root, source_sha)
            self.assertEqual(result["github_run_status"], "RUN_METADATA_MATCH")
            self.assertEqual(result["artifact_status"], "ARCHIVE_CONTENT_MATCH")
            self.assertEqual(result["bounded_semantic_status"], "PASS_BOUNDED")
            self.assertEqual(result["semantic_fitness_hard_gate"], "UNKNOWN")
            self.assertEqual(result["status"], "BOUNDED_MATCH_PRODUCER_UNATTESTED")
            self.assertFalse(result["pareto_eligible"])
            self.assertFalse(result["repository_mutation_authorized"])
            self.assertEqual(result["producer_job_attribution"], "NOT_ATTESTED")
            self.assertEqual(before, git(root, "status", "--porcelain"))

    def test_fitness_projection_can_never_claim_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            result = self.compare(root, source_sha)
            projected = to_fitness_semantic_receipt(
                result, analyzer_sha="d" * 40, profile_sha="e" * 40,
            )
            self.assertEqual(projected["status"], "UNKNOWN")
            self.assertEqual(projected["producer_attestation"], "NOT_ATTESTED")
            self.assertEqual(projected["observed_head_sha"], CANDIDATE_HEAD)
            forged = deepcopy(result)
            forged["semantic_fitness_hard_gate"] = "PASS"
            forged["pareto_eligible"] = True
            # Fake upstream flags never grant Fitness PASS.
            self.assertEqual(
                to_fitness_semantic_receipt(
                    forged, analyzer_sha="d" * 40, profile_sha="e" * 40,
                )["status"], "UNKNOWN",
            )

    def test_fitness_evaluator_excludes_unattested_faster_candidate(self):
        from chatgpt_operation.controller.dea_v01_fitness import evaluate

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            evidence = self.compare(root, source_sha)
            candidate_gate = to_fitness_semantic_receipt(
                evidence, analyzer_sha="d" * 40, profile_sha="e" * 40,
            )
            profile = {
                "analyzer_sha": "d" * 40,
                "profile_sha": "e" * 40,
                "oracle_sha": ORACLE_REV,
                "measurement_set_sha": MEASUREMENTS,
                "hard_gates": ["semantic_contract"],
                "metrics": {"wall_time_ms": "min"},
            }
            def metric(head, value):
                return {
                    "observed_head_sha": head,
                    "analyzer_sha": profile["analyzer_sha"],
                    "profile_sha": profile["profile_sha"],
                    "oracle_sha": profile["oracle_sha"],
                    "measurement_set_sha": profile["measurement_set_sha"],
                    "evidence_ref": "fixture:synthetic",
                    "value": value,
                }
            base = "f" * 40
            manifest = {
                "schema_version": 1, "work_id": "test:dea-evidence",
                "base_sha": base, "profile": profile, "baseline_id": "baseline",
                "candidates": [
                    {
                        "id": "baseline", "head_sha": base, "base_sha": base,
                        "generation": 0,
                        "evidence": {
                            "hard_gates": {
                                "semantic_contract": {
                                    **metric(base, 0), "status": "PASS"
                                }
                            },
                            "metrics": {"wall_time_ms": metric(base, 200)},
                        },
                    },
                    {
                        "id": "A", "head_sha": CANDIDATE_HEAD, "base_sha": base,
                        "generation": 1,
                        "evidence": {
                            "hard_gates": {
                                "semantic_contract": candidate_gate,
                            },
                            "metrics": {
                                "wall_time_ms": metric(CANDIDATE_HEAD, 1),
                            },
                        },
                    },
                ],
            }
            result = evaluate(manifest)
            self.assertEqual(result["candidate_evaluations"]["A"]["state"],
                             "UNKNOWN_HARD_GATE")
            self.assertEqual(result["pareto_review_set"], ["baseline"])
            self.assertIsNone(result["champion"])

    def test_fake_candidate_pass_cannot_upgrade_producer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            result = self.compare(
                root, source_sha, summary={
                    "status": "PASS", "producer_job_attested": True,
                    "champion": True, "fitness_eligible": True,
                }
            )
            self.assertTrue(result["candidate_reported_summary_ignored"])
            self.assertEqual(result["semantic_fitness_hard_gate"], "UNKNOWN")
            self.assertIsNone(result["champion"])

    def test_forged_reference_observation_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            forged = scan_git_snapshot(root, source_sha)
            forged["records"].pop()
            result = self.compare(root, source_sha, observations=forged)
            self.assertEqual(result["semantic_fitness_hard_gate"], "FAIL")
            self.assertEqual(result["status"], "FAILED_OBSERVATION")
            self.assertFalse(result["pareto_eligible"])

    def test_unknown_markdown_semantics_not_promoted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root, unknown=True)
            result = self.compare(root, source_sha)
            self.assertEqual(result["bounded_semantic_status"], "UNKNOWN")
            self.assertEqual(result["semantic_fitness_hard_gate"], "UNKNOWN")

    def test_oracle_protocol_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            with self.assertRaisesRegex(EvidenceGateError, "protocol drift"):
                self.compare(root, source_sha, manifest_override={
                    "oracle_revision_sha": "f" * 40
                })

    def test_wrong_run_workflow_or_unfinished_ci_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            for altered in (
                {"path": ".github/workflows/different.yml"},
                {"head_sha": "f" * 40},
                {"status": "queued", "conclusion": None},
            ):
                run = make_run()
                run.update(altered)
                with self.subTest(altered=altered), self.assertRaises(EvidenceGateError):
                    self.compare(root, source_sha, run=run)

    def test_artifact_not_present_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            data = make_archive(source_sha=source_sha,
                                observations=scan_git_snapshot(root, source_sha))
            listing = make_listing(data, source_sha)
            listing["artifacts"] = []
            listing["total_count"] = 0
            with self.assertRaises(EvidenceGateError):
                self.compare(root, source_sha, listing=listing)

    def test_archive_digest_mismatch_rejected_even_if_json_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            data = make_archive(source_sha=source_sha,
                                observations=scan_git_snapshot(root, source_sha))
            listing = make_listing(data, source_sha)
            listing["artifacts"][0]["digest"] = "sha256:" + "f" * 64
            with self.assertRaises(EvidenceGateError):
                self.compare(root, source_sha, listing=listing)

    def test_source_identity_is_separate_from_candidate_code_sha(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_sha = init_source(root)
            self.assertNotEqual(source_sha, CANDIDATE_HEAD)
            out = self.compare(root, source_sha)
            self.assertEqual(out["candidate_head_sha"], CANDIDATE_HEAD)
            self.assertEqual(out["analyzed_source_sha"], source_sha)


if __name__ == "__main__":
    unittest.main()
