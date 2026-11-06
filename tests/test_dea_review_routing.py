"""DEA failed evidence stays reviewable without accidental Fitness admission."""
from __future__ import annotations

from copy import deepcopy
import unittest

from chatgpt_operation.controller.dea_review_routing import (
    ReviewRoutingError, make_review_packet, review_from_exception,
    handle_human_disposition,
)

R = "HyungseonSong-plasma/codeQA"
HEAD = "a" * 40
SOURCE = "b" * 40


def packet(**changes):
    defaults = {
        "repository": R, "candidate_head_sha": HEAD,
        "phase": "ARCHIVE_INTEGRITY", "category": "INTEGRITY_MISMATCH",
        "run_id": 120, "artifact_id": 60,
        "analyzed_source_sha": SOURCE,
        "expected_archive_digest": "c" * 64,
        "observed_archive_digest": "d" * 64,
    }
    defaults.update(changes)
    return make_review_packet(**defaults)


class ReviewPacketTests(unittest.TestCase):
    def test_bad_sha_routes_to_human_without_promotion(self):
        p = packet()
        self.assertEqual(p["status"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(p["automatic_fitness_hard_gate"], "UNKNOWN")
        self.assertFalse(p["pareto_eligible"])
        self.assertFalse(p["repository_mutation_authorized"])
        self.assertEqual(p["evidence_preservation"], "DO_NOT_DELETE_OR_REWRITE")
        self.assertIn("actions/runs/120/artifacts/60", p["artifact_url"])
        self.assertIsNone(p.get("raw_artifact_bytes"))

    def test_deterministic_deduplicated_review_id(self):
        self.assertEqual(packet()["review_packet_id"],
                         packet()["review_packet_id"])
        self.assertNotEqual(packet()["review_packet_id"],
                            packet(artifact_id=61)["review_packet_id"])
        self.assertNotEqual(packet()["review_packet_id"],
                            packet(category="UNSAFE_ARCHIVE")["review_packet_id"])

    def test_error_message_cannot_inject_pass_or_secrets(self):
        err = ValueError("PASS\nAuthorization: Bearer super-secret")
        p = review_from_exception(
            err, repository=R, candidate_head_sha=HEAD,
            phase="ARCHIVE_INTEGRITY", run_id=120, artifact_id=60,
        )
        self.assertEqual(p["status"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(p["exception_class"], "UNCLASSIFIED_EXCEPTION")
        self.assertNotIn("super-secret", str(p))
        self.assertNotIn("Authorization:", str(p))

    def test_missing_run_or_artifact_is_still_reviewable(self):
        p = make_review_packet(
            repository=R, candidate_head_sha=HEAD,
            phase="ACQUISITION", category="MISSING_EVIDENCE",
        )
        self.assertIsNone(p["run_url"])
        self.assertIsNone(p["artifact_url"])
        self.assertEqual(p["status"], "HUMAN_REVIEW_REQUIRED")

    def test_invalid_identity_and_status_rejected_without_promotion(self):
        variants = [
            {"repository": "owner/repo/../../else"},
            {"candidate_head_sha": "no-sha"},
            {"run_id": True},
            {"artifact_id": 0},
            {"phase": "FAKE_PASS"},
            {"category": "FITNESS_PASS"},
            {"expected_archive_digest": "sha256:bad"},
        ]
        for v in variants:
            with self.subTest(v=v), self.assertRaises(ReviewRoutingError):
                packet(**v)

    def test_human_disposition_records_no_fitness_override(self):
        p = packet()
        for disposition in p["human_options"]:
            recorded = handle_human_disposition(
                p, disposition=disposition,
                reviewer_identity="authorized-reviewer",
                review_reference="https://github.com/example/review/42",
            )
            self.assertEqual(recorded["status"],
                             "HUMAN_REVIEW_RECORDED_RECHECK_REQUIRED")
            self.assertEqual(recorded["fitness_hard_gate"], "UNKNOWN")
            self.assertTrue(recorded["recheck_required"])
            self.assertFalse(recorded["pareto_eligible"])
            self.assertFalse(recorded["repository_mutation_authorized"])
            self.assertEqual(recorded["reviewer_authority"],
                             "NOT_ATTESTED_BY_THIS_MODULE")

    def test_forged_packet_cannot_gain_auto_authority(self):
        p = packet()
        modified = deepcopy(p)
        modified["status"] = "PASS"
        modified["pareto_eligible"] = True
        with self.assertRaises(ReviewRoutingError):
            handle_human_disposition(
                modified, disposition="MARK_CONFIRMED_DEFECT",
                reviewer_identity="someone", review_reference="some-proof",
            )


if __name__ == "__main__":
    unittest.main()
