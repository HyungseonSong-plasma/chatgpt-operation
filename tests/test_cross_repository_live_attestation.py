"""Adversarial live target readback tests; no GitHub mutations."""
import unittest
from dataclasses import replace

from chatgpt_operation.controller.cross_repository_policy import TargetRequest
from chatgpt_operation.controller.cross_repository_live_attestation import attest_live_target

SHA = "a" * 40
REPO = "owner/codeQA"
POLICY = {
    "schema_version": 1, "enabled": True,
    "repository": REPO, "repository_id": 42,
    "base_branch": "main", "head_branch": "samuel/preflight",
    "base_sha": SHA, "path_prefixes": ["docs/samuel/"],
    "workflows": ["layout.yml"],
    "operations": ["branch.create", "file.create", "pr.create", "ci.inspect"],
    "merge_enabled": False,
}
REQUEST = TargetRequest(
    REPO, 42, "main", "samuel/preflight", SHA,
    ("docs/samuel/witness.md",), ("layout.yml",),
    ("branch.create", "file.create", "pr.create", "ci.inspect"),
)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.responses = {
            "/repos/owner/codeQA": {
                "id": 42, "full_name": REPO, "default_branch": "main",
                "permissions": {"pull": True, "push": True},
            },
            "/repos/owner/codeQA/git/ref/heads/main": {
                "ref": "refs/heads/main", "object": {"sha": SHA},
            },
            "/repos/owner/codeQA/actions/workflows/layout.yml": {
                "path": ".github/workflows/layout.yml", "state": "active",
            },
        }

    def get(self, path):
        self.calls.append(path)
        return self.responses[path]


class LiveAttestationTests(unittest.TestCase):
    def assert_denied(self, transport, request=REQUEST, policy=POLICY, authenticated=True):
        result = attest_live_target(
            request, policy, transport=transport,
            independent_authorization_verified=authenticated,
        )
        self.assertFalse(result.ready)
        self.assertTrue(result.reasons)
        return result

    def test_valid_live_readback_is_only_precondition(self):
        transport = FakeTransport()
        result = attest_live_target(
            REQUEST, POLICY, transport=transport,
            independent_authorization_verified=True,
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.observed_repository_id, 42)
        self.assertEqual(result.observed_base_sha, SHA)
        self.assertEqual(len(transport.calls), 3)

    def test_absent_independent_authorization_never_calls_transport(self):
        transport = FakeTransport()
        result = self.assert_denied(transport, authenticated=False)
        self.assertIn("independent_authorization_missing", result.reasons)
        self.assertEqual(transport.calls, [])

    def test_disabled_candidate_policy_stays_blocked(self):
        t = FakeTransport()
        self.assert_denied(t, policy={**POLICY, "enabled": False})
        self.assertEqual(t.calls, [])

    def test_stale_expected_sha_stops_before_readback(self):
        t = FakeTransport()
        self.assert_denied(t, request=replace(REQUEST, base_sha="b" * 40))
        self.assertEqual(t.calls, [])

    def test_live_sha_move_denied(self):
        t = FakeTransport()
        t.responses["/repos/owner/codeQA/git/ref/heads/main"]["object"]["sha"] = "b" * 40
        result = self.assert_denied(t)
        self.assertIn("live_base_sha_mismatch", result.reasons)

    def test_repo_identity_spoof_denied(self):
        for field, value in (("id", 99), ("full_name", "owner/other")):
            with self.subTest(field=field):
                t = FakeTransport()
                t.responses["/repos/owner/codeQA"][field] = value
                self.assertIn("target_repository_identity_mismatch", self.assert_denied(t).reasons)

    def test_missing_push_permission_denied(self):
        for permissions in ({}, {"push": False}, None):
            with self.subTest(permissions=permissions):
                t = FakeTransport()
                t.responses["/repos/owner/codeQA"]["permissions"] = permissions
                self.assertIn("target_token_push_not_attested", self.assert_denied(t).reasons)

    def test_renamed_or_disabled_workflow_denied(self):
        for key, value in (("path", ".github/workflows/renamed.yml"), ("state", "disabled_manually")):
            with self.subTest(key=key):
                t = FakeTransport()
                t.responses["/repos/owner/codeQA/actions/workflows/layout.yml"][key] = value
                self.assertIn("workflow_not_active:layout.yml", self.assert_denied(t).reasons)

    def test_network_or_auth_error_denied(self):
        t = FakeTransport()
        del t.responses["/repos/owner/codeQA"]
        self.assertIn("target_readback_failed", self.assert_denied(t).reasons)

    def test_deny_merge_operation_before_readback(self):
        t = FakeTransport()
        result = self.assert_denied(
            t, request=replace(REQUEST, operations=("pr.merge",)),
        )
        self.assertIn("unsafe_operation", result.reasons)
        self.assertEqual(t.calls, [])

    def test_missing_exact_workflow_scope(self):
        t = FakeTransport()
        self.assert_denied(t, request=replace(REQUEST, workflows=("renamed.yml",)))
        self.assertEqual(t.calls, [])

    def test_default_branch_mismatch(self):
        t = FakeTransport()
        t.responses["/repos/owner/codeQA"]["default_branch"] = "development"
        self.assertIn("target_default_branch_mismatch", self.assert_denied(t).reasons)
