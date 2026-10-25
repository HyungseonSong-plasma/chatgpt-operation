"""Adverse preflight tests; no live repository mutation."""
import unittest
from dataclasses import replace

from chatgpt_operation.controller.cross_repository_policy import (
    TargetRequest, validate_target_request,
)

SHA = "a" * 40
POLICY = {
    "schema_version": 1, "enabled": True,
    "repository": "HyungseonSong-plasma/codeQA", "repository_id": 123,
    "base_branch": "samuel/preflight", "base_sha": SHA,
    "path_prefixes": ["docs/"], "workflows": ["CI"],
    "operations": ["branch.create", "file.create", "pr.create", "ci.inspect"],
    "merge_enabled": False,
}
REQUEST = TargetRequest(
    "HyungseonSong-plasma/codeQA", 123, "samuel/preflight", SHA,
    ("docs/preflight.md",), ("CI",), ("branch.create", "file.create", "pr.create", "ci.inspect"),
)


class TargetPolicyTests(unittest.TestCase):
    def check_denied(self, request=REQUEST, policy=None, **kw):
        result = validate_target_request(request, POLICY if policy is None else policy,
                                         authorization_verified=kw.get("authorization_verified", True))
        self.assertFalse(result.allowed)
        self.assertTrue(result.reasons)

    def test_valid_bounded_request(self):
        self.assertTrue(validate_target_request(REQUEST, POLICY, authorization_verified=True).allowed)

    def test_authorization_absent(self):
        self.check_denied(authorization_verified=False)

    def test_disabled_policy(self):
        self.check_denied(policy={**POLICY, "enabled": False})

    def test_wrong_repository_or_identity(self):
        self.check_denied(replace(REQUEST, repository="someone/other"))
        self.check_denied(replace(REQUEST, repository_id=124))
        self.check_denied(replace(REQUEST, repository_id=True))

    def test_stale_or_malformed_sha(self):
        self.check_denied(replace(REQUEST, base_sha="b" * 40))
        self.check_denied(replace(REQUEST, base_sha="main"))

    def test_wrong_branch(self):
        self.check_denied(replace(REQUEST, base_branch="main"))

    def test_unknown_workflow(self):
        self.check_denied(replace(REQUEST, workflows=("Renamed CI",)))

    def test_unsafe_operations_and_merge(self):
        self.check_denied(replace(REQUEST, operations=("pr.merge",)))
        self.check_denied(policy={**POLICY, "merge_enabled": True})

    def test_path_traversal_and_prefix_collision(self):
        for path in ("docs/../src/secret.py", "docs2/readme.md", "/docs/readme.md",
                     "docs//bad.md", "docs\\bad.md"):
            with self.subTest(path=path):
                self.check_denied(replace(REQUEST, paths=(path,)))

    def test_missing_and_malformed_allowlists(self):
        self.check_denied(policy={**POLICY, "workflows": []})
        self.check_denied(policy={**POLICY, "path_prefixes": []})
        self.check_denied(replace(REQUEST, paths=()))
