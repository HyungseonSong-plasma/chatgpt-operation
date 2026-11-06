"""Negative tests and mocked end-to-end calls for DEA's opt-in write adapter."""
from __future__ import annotations

import base64
import copy
from hashlib import sha1
import json
from pathlib import Path
import unittest

from chatgpt_operation.controller.dea_trusted_workflow_authoring_adapter import (
    BRANCH, PATH, POLICY_PATH, REFERENCE_PATH, REPO,
    TrustedWorkflowDraftAdapter, WorkflowAuthoringError,
)
from chatgpt_operation.repository.blocker_gate import (
    BlockerGateError, CommonPreWriteGate, GateDecision,
)
from chatgpt_operation.repository.mutation import ApiError


ROOT = Path(__file__).resolve().parents[1]
YAML = (ROOT / REFERENCE_PATH).read_bytes()
ORIGINAL_POLICY = json.loads((ROOT / POLICY_PATH).read_text())
SHA = "a" * 40
CREATED_SHA = "b" * 40


def scoped_policy():
    doc = copy.deepcopy(ORIGINAL_POLICY)
    paths = doc["mutation"]["file_paths"]
    if PATH not in paths["allow"]:
        paths["allow"].append(PATH)
    paths["deny"] = [x for x in paths["deny"] if x != ".github/workflows/**"]
    return doc


def gh_blob(content: bytes, path: str) -> dict:
    ident = sha1(b"blob " + str(len(content)).encode() + b"\x00" + content)
    return {
        "path": path,
        "sha": ident.hexdigest(),
        "encoding": "base64",
        "content": base64.b64encode(content).decode(),
    }


def guard(*, allow=True):
    # The mock is limited to isolated tests. Production must instantiate
    # a real CommonPreWriteGate with trusted, persisted journal/checkpoint.
    g = object.__new__(CommonPreWriteGate)

    def _require_clear(*, logical_intent_id, expected_head_sha):
        if not allow:
            raise BlockerGateError("ACTIVE_BLOCKER_REPOSITORY_POLICY")
        assert expected_head_sha == SHA
        assert len(logical_intent_id) == 64
        return GateDecision(True, "NO_ACTIVE_BLOCKER_NOT_AUTHORIZATION", 2, "tip")
    g.require_clear = _require_clear
    return g


class FakeTrustedGitHub:
    repository = REPO

    def __init__(self, *, policy=None):
        self.main = SHA
        self.policy = (scoped_policy() if policy is None else policy)
        self.yaml = YAML
        self.branch = None
        self.file = None
        self.pr = None
        self.writes: list[tuple[str, str, dict]] = []
        self.corrupt_readback = False

    def get(self, path, *, query=None):
        if path == "/git/ref/heads/main":
            return {"ref": "refs/heads/main", "object": {"sha": self.main}}
        if path == "/contents/" + POLICY_PATH:
            if query != {"ref": self.main}:
                raise AssertionError("policy must be from exact main")
            return gh_blob(json.dumps(self.policy).encode(), POLICY_PATH)
        if path == "/contents/" + REFERENCE_PATH:
            if query != {"ref": self.main}:
                raise AssertionError("reference must be from exact main")
            return gh_blob(self.yaml, REFERENCE_PATH)
        if path == "/git/ref/heads/" + BRANCH:
            if self.branch is None:
                raise ApiError("not found", status=404)
            return {"ref": "refs/heads/" + BRANCH,
                    "object": {"sha": self.branch}}
        if path == "/contents/" + PATH:
            if query != {"ref": BRANCH}:
                raise AssertionError("file check must be on exact branch")
            if self.file is None:
                raise ApiError("not found", status=404)
            return gh_blob(
                b"tampered" if self.corrupt_readback else self.file, PATH
            )
        if path == "/pulls":
            assert query == {
                "state": "open", "head": "HyungseonSong-plasma:" + BRANCH,
                "base": "main", "per_page": "100",
            }
            return [] if self.pr is None else [self.pr]
        if path == "/pulls/99":
            return self.pr
        raise AssertionError("unapproved read endpoint " + path)

    def request(self, method, path, *, payload=None):
        self.writes.append((method, path, payload))
        if method == "POST" and path == "/git/refs":
            if self.branch is not None:
                raise AssertionError("cannot recreate existing branch")
            assert payload == {
                "ref": "refs/heads/" + BRANCH,
                "sha": SHA,
            }
            self.branch = SHA
            return {"ref": payload["ref"], "object": {"sha": SHA}}
        if method == "PUT" and path == "/contents/" + PATH:
            assert payload["branch"] == BRANCH
            self.file = base64.b64decode(payload["content"])
            self.branch = CREATED_SHA
            return {"commit": {"sha": CREATED_SHA}}
        if method == "POST" and path == "/pulls":
            assert payload["draft"] is True
            assert payload["base"] == "main"
            assert payload["head"] == BRANCH
            self.pr = {
                "number": 99, "draft": True, "state": "open", "merged": False,
                "head": {"ref": BRANCH, "sha": self.branch},
                "base": {"ref": "main", "sha": self.main},
                "html_url": "https://github.com/" + REPO + "/pull/99",
            }
            return {"number": 99}
        raise AssertionError("unapproved GitHub write route")


class TrustedWorkflowDraftAdapterTests(unittest.TestCase):
    def test_exact_human_reviewed_scope_creates_only_draft(self):
        api = FakeTrustedGitHub()
        result = TrustedWorkflowDraftAdapter(
            transport=api, blocker_gate=guard()
        ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(result.status, "DRAFT_PR_CREATED_REVIEW_REQUIRED")
        self.assertEqual(result.pr_number, 99)
        self.assertEqual(result.head_sha, CREATED_SHA)
        self.assertFalse(result.merged)
        self.assertFalse(result.executable_authority)
        self.assertEqual(
            [(method, path) for method, path, _ in api.writes],
            [
                ("POST", "/git/refs"),
                ("PUT", "/contents/" + PATH),
                ("POST", "/pulls"),
            ],
        )
        self.assertEqual(api.file, YAML)

    def test_repository_native_credential_cannot_be_used_here(self):
        api = FakeTrustedGitHub()
        api.repository = "someone/another-repo"
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "FOREIGN_GITHUB_TRANSPORT"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            )
        self.assertEqual(api.writes, [])

    def test_missing_real_blocker_gate_fails_before_any_write(self):
        api = FakeTrustedGitHub()
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "TRUSTED_GATE_REQUIRED"
        ):
            TrustedWorkflowDraftAdapter(transport=api, blocker_gate=None)
        self.assertEqual(api.writes, [])

    def test_denied_human_adoption_policy_never_writes(self):
        api = FakeTrustedGitHub(policy=ORIGINAL_POLICY)
        adapter = TrustedWorkflowDraftAdapter(
            transport=api, blocker_gate=guard()
        )
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "EXACT_PATH_POLICY_NOT_ADOPTED"
        ):
            adapter.prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_blocker_gate_failure_stops_before_any_write(self):
        api = FakeTrustedGitHub()
        adapter = TrustedWorkflowDraftAdapter(
            transport=api, blocker_gate=guard(allow=False)
        )
        with self.assertRaises(BlockerGateError):
            adapter.prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_stale_main_or_wrong_sha_never_writes(self):
        api = FakeTrustedGitHub()
        adapter = TrustedWorkflowDraftAdapter(
            transport=api, blocker_gate=guard()
        )
        for sha in ("c"*40, "HEAD", ""):
            with self.subTest(sha=sha), self.assertRaises(
                WorkflowAuthoringError
            ):
                adapter.prepare_and_create_draft(expected_main_sha=sha)
        self.assertEqual(api.writes, [])

    def test_existing_branch_at_different_sha_rejected(self):
        api = FakeTrustedGitHub()
        api.branch = "c" * 40
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "BRANCH_EXISTS_AT_UNRELATED_SHA"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_existing_file_is_never_overwritten(self):
        api = FakeTrustedGitHub()
        api.branch = SHA
        api.file = b"untrusted"
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "TARGET_FILE_ALREADY_EXISTS"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_existing_open_pr_rejected_before_writes(self):
        api = FakeTrustedGitHub()
        api.pr = {
            "number": 123, "head": {"ref": BRANCH},
            "base": {"ref": "main"},
        }
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "PR_ALREADY_OPEN_FOR_BRANCH"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_bad_git_blob_readback_is_never_trusted(self):
        class BadBlob(FakeTrustedGitHub):
            def get(self, path, *, query=None):
                result = super().get(path, query=query)
                if path == "/contents/" + POLICY_PATH:
                    result["sha"] = "d" * 40
                return result
        api = BadBlob()
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "GITHUB_CONTENT_BLOB_SHA_MISMATCH"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_main_blueprint_changed_without_review_is_denied(self):
        api = FakeTrustedGitHub()
        api.yaml = YAML + b"\n# unauthorized later revision\n"
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "REVIEWED_WORKFLOW_BLUEPRINT_CHANGED"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_modified_file_readback_does_not_open_pr(self):
        api = FakeTrustedGitHub()
        api.corrupt_readback = True
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "CREATED_WORKFLOW_BYTES_MISMATCH"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(
            [m for m, _, _ in api.writes], ["POST", "PUT"]
        )
        self.assertIsNone(api.pr)

    def test_policy_wildcard_denied_before_write(self):
        api = FakeTrustedGitHub()
        api.policy["mutation"]["file_paths"]["allow"].append(
            ".github/workflows/ci.yml"
        )
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "EXACT_PATH_POLICY_NOT_ADOPTED"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=guard()
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])

    def test_main_sha_move_during_gate_prevents_mutation(self):
        api = FakeTrustedGitHub()
        g = guard()
        first = [0]

        def move_main(*, logical_intent_id, expected_head_sha):
            first[0] += 1
            if first[0] == 1:
                api.main = "d" * 40
            return GateDecision(True, "TEST_ONLY", 1, "tip")
        g.require_clear = move_main
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "MAIN_MOVED_AFTER_GATE"
        ):
            TrustedWorkflowDraftAdapter(
                transport=api, blocker_gate=g
            ).prepare_and_create_draft(expected_main_sha=SHA)
        self.assertEqual(api.writes, [])


if __name__ == "__main__":
    unittest.main()
