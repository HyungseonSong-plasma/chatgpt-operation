"""Evidence-gated release tests: technical recovery != policy authority."""
import unittest

from chatgpt_operation.repository.blocker_triage import (
    BlockerObservation, BlockerSource, logical_intent_id,
)
from chatgpt_operation.repository.blocker_resolution import (
    BlockerState, ClearanceEvidence, ClearanceKind, evaluate_clearance,
)

SHA = "b" * 40
OTHER_SHA = "a" * 40
INTENT = logical_intent_id(
    repository="HyungseonSong-plasma/chatgpt-operation",
    branch="samuel/236-mutation-blocker-taxonomy",
    work_id="issue-236",
    paths=("src/chatgpt_operation/repository/blocker_resolution.py",),
)


def blocker(source, *, status=None):
    return BlockerObservation(source, INTENT, "github-connector", "deny-1", status)


def proof(kind, *, head=SHA, intent=INTENT, origin="deny-1", ref="readback-2"):
    return ClearanceEvidence(intent, origin, kind, head, ref)


def accept(*_):
    return True


class MutationBlockerResolutionTests(unittest.TestCase):
    def test_technical_blockers_auto_resolve_only_with_matching_verified_proof(self):
        cases = (
            (BlockerSource.STALE_IDENTITY, ClearanceKind.SHA_REPLANNED),
            (BlockerSource.WORKFLOW_GOVERNANCE, ClearanceKind.WORKFLOW_PROVENANCE_PASS),
            (BlockerSource.CI, ClearanceKind.EXACT_HEAD_CI_PASS),
            (BlockerSource.REVIEW, ClearanceKind.CURRENT_HEAD_REVIEW),
        )
        for source, kind in cases:
            with self.subTest(source=source):
                result = evaluate_clearance(blocker(source), proof(kind),
                                            expected_head_sha=SHA, verify_technical=accept)
                self.assertEqual(result.state, BlockerState.RESOLVED_AUTOMATICALLY)
                self.assertFalse(result.write_authorized)
                self.assertEqual(result.blocker_evidence_ref, "deny-1")
                self.assertEqual(result.clearance_evidence_ref, "readback-2")

    def test_github_access_401_403_404_needs_sufficient_scoped_readback_not_human_approval(self):
        for status in (401, 403, 404):
            with self.subTest(status=status):
                b = blocker(BlockerSource.GITHUB_HTTP, status=status)
                self.assertEqual(
                    evaluate_clearance(b, proof(ClearanceKind.TARGET_ACCESS_RESTORED),
                                       expected_head_sha=SHA, verify_technical=accept).state,
                    BlockerState.RESOLVED_AUTOMATICALLY,
                )
                self.assertEqual(
                    evaluate_clearance(b, proof(ClearanceKind.TARGET_ACCESS_RESTORED),
                                       expected_head_sha=SHA).state,
                    BlockerState.ACTIVE,
                )

    def test_transient_retry_and_sha_conflict_have_distinct_automatic_proofs(self):
        for status in (409, 412, 422):
            self.assertEqual(
                evaluate_clearance(
                    blocker(BlockerSource.GITHUB_HTTP, status=status),
                    proof(ClearanceKind.SHA_REPLANNED), expected_head_sha=SHA,
                    verify_technical=accept).state,
                BlockerState.RESOLVED_AUTOMATICALLY)
        for status in (429, 500, 502, 503, 504):
            self.assertEqual(
                evaluate_clearance(
                    blocker(BlockerSource.GITHUB_HTTP, status=status),
                    proof(ClearanceKind.TRANSIENT_RECOVERED), expected_head_sha=SHA,
                    verify_technical=accept).state,
                BlockerState.RESOLVED_AUTOMATICALLY)

    def test_owner_policy_requires_authority_not_generic_technical_verifier(self):
        b = blocker(BlockerSource.REPOSITORY_POLICY)
        p = proof(ClearanceKind.OWNER_POLICY_AUTHORIZED)
        self.assertEqual(evaluate_clearance(
            b, p, expected_head_sha=SHA, verify_technical=accept).state,
            BlockerState.ESCALATED)
        self.assertEqual(evaluate_clearance(
            b, p, expected_head_sha=SHA, verify_authority=accept).state,
            BlockerState.RESOLVED_BY_AUTHORITY)

    def test_external_tool_safety_denial_requires_upstream_clearance(self):
        b = blocker(BlockerSource.TOOL_SAFETY)
        p = proof(ClearanceKind.UPSTREAM_SAFETY_CLEARED)
        for kwargs in ({}, {"verify_technical": accept},
                       {"verify_authority": lambda e: False}):
            with self.subTest(kwargs=tuple(kwargs)):
                self.assertEqual(evaluate_clearance(b, p, expected_head_sha=SHA,
                                                    **kwargs).state, BlockerState.ESCALATED)
        self.assertEqual(evaluate_clearance(
            b, p, expected_head_sha=SHA, verify_authority=accept).state,
            BlockerState.RESOLVED_BY_AUTHORITY)

    def test_self_attested_claim_without_trusted_verifier_never_releases(self):
        b = blocker(BlockerSource.CI)
        p = proof(ClearanceKind.EXACT_HEAD_CI_PASS)
        outcome = evaluate_clearance(b, p, expected_head_sha=SHA)
        self.assertEqual(outcome.state, BlockerState.ACTIVE)
        self.assertEqual(outcome.reason, "TRUSTED_VERIFIER_UNAVAILABLE")

    def test_old_sha_and_changed_logical_intent_cannot_clear(self):
        b = blocker(BlockerSource.CI)
        mismatches = (
            proof(ClearanceKind.EXACT_HEAD_CI_PASS, head=OTHER_SHA),
            proof(ClearanceKind.EXACT_HEAD_CI_PASS, intent="c" * 64),
            proof(ClearanceKind.EXACT_HEAD_CI_PASS, origin="another-blocker"),
            proof(ClearanceKind.SHA_REPLANNED),
        )
        for p in mismatches:
            with self.subTest(proof=p):
                self.assertEqual(evaluate_clearance(
                    b, p, expected_head_sha=SHA,
                    verify_technical=accept).state, BlockerState.ACTIVE)

    def test_wrong_type_of_clearance_cannot_clear_external_safety(self):
        b = blocker(BlockerSource.TOOL_SAFETY)
        self.assertEqual(
            evaluate_clearance(b, proof(ClearanceKind.TARGET_ACCESS_RESTORED),
                               expected_head_sha=SHA, verify_authority=accept).state,
            BlockerState.ESCALATED)

    def test_verifier_error_false_or_nonboolean_fails_closed(self):
        def crashes(_):
            raise RuntimeError("readback unavailable")
        b = blocker(BlockerSource.CI)
        for fn in (crashes, lambda _: False, lambda _: 1, lambda _: "PASS"):
            with self.subTest(fn=fn):
                self.assertEqual(evaluate_clearance(
                    b, proof(ClearanceKind.EXACT_HEAD_CI_PASS), expected_head_sha=SHA,
                    verify_technical=fn).state, BlockerState.ACTIVE)

    def test_unknown_or_transport_blockers_not_automatically_cleared(self):
        for source in (BlockerSource.UNKNOWN, BlockerSource.PROVIDER_TRANSPORT):
            with self.subTest(source=source):
                self.assertEqual(
                    evaluate_clearance(blocker(source), proof(ClearanceKind.EXACT_HEAD_CI_PASS),
                                       expected_head_sha=SHA, verify_technical=accept).state,
                    BlockerState.ESCALATED)

    def test_no_evidence_keeps_technical_blocker_active(self):
        result = evaluate_clearance(blocker(BlockerSource.CI), None,
                                    expected_head_sha=SHA, verify_technical=accept)
        self.assertEqual(result.state, BlockerState.ACTIVE)

    def test_invalid_evidence_rejected(self):
        with self.assertRaises(ValueError):
            proof(ClearanceKind.EXACT_HEAD_CI_PASS, head="not-a-sha")
        with self.assertRaises(ValueError):
            proof(ClearanceKind.EXACT_HEAD_CI_PASS, ref="deny-1")
        with self.assertRaises(ValueError):
            proof(ClearanceKind.EXACT_HEAD_CI_PASS, intent="invalid")
        with self.assertRaises(ValueError):
            proof("fake")
        with self.assertRaises(ValueError):
            evaluate_clearance(blocker(BlockerSource.CI),
                               proof(ClearanceKind.EXACT_HEAD_CI_PASS),
                               expected_head_sha="bad", verify_technical=accept)

    def test_state_machine_never_grants_mutation_authority(self):
        b = blocker(BlockerSource.TOOL_SAFETY)
        result = evaluate_clearance(b, proof(ClearanceKind.UPSTREAM_SAFETY_CLEARED),
                                    expected_head_sha=SHA, verify_authority=accept)
        self.assertFalse(result.write_authorized)
        self.assertEqual(result.state, BlockerState.RESOLVED_BY_AUTHORITY)
        self.assertEqual(BlockerState.SUPERSEDED.value, "SUPERSEDED")
        self.assertEqual(BlockerState.ACTIVE.value, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
