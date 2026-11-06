"""Negative/positive evidence-coverage tests; never semantic certification."""
import unittest

from chatgpt_operation.documentation.evidence_audit_v02 import audit_evidence_v02
from chatgpt_operation.documentation.status_labels import LabelError

SHA = "a" * 40
OLD = "b" * 40
DECLARED = {"decision": "ADOPTED", "implementation": "IMPLEMENTED", "review": "REVIEWED"}
KINDS = {"decision": "ADR", "implementation": "SOURCE", "review": "INDEPENDENT_REVIEW"}


def witness(axis, **changes):
    result = {"kind": KINDS[axis], "repository": "owner/consumer",
              "path": "docs/adr.md" if axis == "decision" else "src/feature.py",
              "revision": SHA, "scope": "bounded-feature-A", "provenance": "owner"}
    if axis == "review":
        result["reviewer"] = "independent-reviewer"
    result.update(changes)
    return result


def run(declared=None, witnesses=None, verified=None, snapshot_sha=SHA):
    return audit_evidence_v02(
        declared=DECLARED if declared is None else declared,
        snapshot_sha=snapshot_sha,
        witnesses={axis: witness(axis) for axis in DECLARED} if witnesses is None else witnesses,
        independently_verified={axis: True for axis in DECLARED} if verified is None else verified,
    )


class EvidenceAuditV02Tests(unittest.TestCase):
    def test_exact_witness_coverage_is_not_semantic_certification(self):
        result = run()
        self.assertEqual(result.status, "EVIDENCE_COVERED")
        self.assertEqual(result.verified, DECLARED)
        self.assertEqual(result.issues, ())
        self.assertEqual(result.revalidation_queue, ())

    def test_missing_witness_requires_revalidation(self):
        result = run(witnesses={"decision": witness("decision")})
        self.assertEqual(result.verified["implementation"], "NOT_EVALUATED")
        self.assertEqual(result.verified["review"], "NOT_EVALUATED")
        self.assertIn("review:MISSING_EVIDENCE", result.issues)
        self.assertEqual(result.revalidation_queue, ("implementation", "review"))

    def test_stale_sha_is_not_promoted(self):
        result = run(witnesses={**{a: witness(a) for a in DECLARED},
                                "implementation": witness("implementation", revision=OLD)})
        self.assertIn("implementation:STALE_EVIDENCE", result.issues)
        self.assertEqual(result.verified["implementation"], "NOT_EVALUATED")

    def test_wrong_kind_and_unverified_evidence(self):
        result = run(witnesses={**{a: witness(a) for a in DECLARED},
                                "decision": witness("decision", kind="SOURCE")},
                     verified={"decision": True, "implementation": False, "review": True})
        self.assertIn("decision:WRONG_EVIDENCE_KIND", result.issues)
        self.assertIn("implementation:VERIFICATION_REQUIRED", result.issues)

    def test_self_review_is_not_independent(self):
        result = run(witnesses={**{a: witness(a) for a in DECLARED},
                                "review": witness("review", reviewer="owner")})
        self.assertIn("review:INDEPENDENCE_NOT_ATTESTED", result.issues)
        self.assertEqual(result.verified["review"], "NOT_EVALUATED")

    def test_missing_provenance_and_bad_revision(self):
        result = run(witnesses={**{a: witness(a) for a in DECLARED},
                                "decision": witness("decision", scope=""),
                                "implementation": witness("implementation", revision="main")})
        self.assertIn("decision:INCOMPLETE_PROVENANCE", result.issues)
        self.assertIn("implementation:INVALID_EVIDENCE_SHA", result.issues)

    def test_unknown_and_not_evaluated_are_not_upgraded(self):
        declared = {"decision": "NOT_EVALUATED", "implementation": "NOT_EVALUATED",
                    "review": "NOT_EVALUATED"}
        result = run(declared=declared, witnesses={}, verified={})
        self.assertEqual(set(result.verified.values()), {"NOT_EVALUATED"})
        self.assertEqual(result.status, "EVIDENCE_COVERED")

    def test_unsupported_unknown_claim_fails_closed(self):
        with self.assertRaises(LabelError):
            run(declared=dict(DECLARED, decision="UNKNOWN"))
        with self.assertRaises(LabelError):
            run(snapshot_sha="main")

    def test_extra_axes_fail_closed(self):
        with self.assertRaises(LabelError):
            run(witnesses={"other": witness("decision")})

    def test_unneeded_witness_is_flagged(self):
        declared = dict(DECLARED, decision="PROPOSED")
        result = run(declared=declared)
        self.assertIn("decision:WITNESS_WITHOUT_POSITIVE_CLAIM", result.issues)


if __name__ == "__main__":
    unittest.main()
