"""Trusted host entrypoint integration tests using deterministic fakes only.

All tests run without GitHub credentials or real network access. Positive
test proves the internal transport -> journal -> gate -> broker wiring,
NOT that ChatGPT's hosted GitHub connector was reconfigured.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
from pathlib import Path
import unittest

from chatgpt_operation.github.dea_workflow_authoring_dispatch import (
    HostOwnedTrustConfig, connect_hosted_dea_workflow_authoring,
)
from chatgpt_operation.controller.dea_trusted_workflow_authoring_adapter import (
    BRANCH, PATH, POLICY_PATH, REFERENCE_PATH, REPO, WORK_ID,
    WorkflowAuthoringError,
)
from chatgpt_operation.controller.dea_operator_delegation import (
    ACTION, DELEGATE_ID, OPERATOR_LOGIN,
    OperatorDelegationError, OperatorDelegationGrant,
)
from chatgpt_operation.repository.blocker_checkpoint import JournalCheckpoint
from chatgpt_operation.repository.blocker_journal import (
    MARKER, ZERO, _canonical, _event_hash,
)
from chatgpt_operation.repository.blocker_gate import BlockerGateError
from chatgpt_operation.repository.blocker_triage import logical_intent_id
from chatgpt_operation.repository.mutation import ApiError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / REFERENCE_PATH).read_bytes()
DEFAULT_POLICY = json.loads((ROOT / POLICY_PATH).read_text())
MAIN_SHA = "a" * 40
PR_SHA = "b" * 40
ISSUE = 236
ACTOR = "trusted-journal-app"


def restricted_policy():
    policy = copy.deepcopy(DEFAULT_POLICY)
    paths = policy["mutation"]["file_paths"]
    if PATH not in paths["allow"]:
        paths["allow"].append(PATH)
    paths["deny"] = [p for p in paths["deny"] if p != ".github/workflows/**"]
    return policy


def blob(data, path):
    digest = sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()
    return {
        "path": path, "sha": digest,
        "content": base64.b64encode(data).decode(), "encoding": "base64",
    }


class FakeGitHubTransport:
    repository = REPO

    def __init__(self, *, policy=None):
        self.policy = restricted_policy() if policy is None else policy
        self.main = MAIN_SHA
        self.branch = None
        self.file = None
        self.pr = None
        self.yaml = SOURCE
        self.writes = []
        self.events = []
        self.created_commit_parent = MAIN_SHA
        self.created_commit_files = [{"filename": PATH, "status": "added"}]
        self._last_tip = ZERO
        self._last_sequence = 0
        self.register_event({
            "event": "REGISTERED",
            "intent": logical_intent_id(
                repository=REPO, branch=BRANCH, work_id=WORK_ID,
                paths=(PATH,)
            ),
            "head": MAIN_SHA, "evidence_ref": "trusted-controller-registration",
        })

    def register_event(self, payload):
        next_sequence = self._last_sequence + 1
        tip = _event_hash(next_sequence, self._last_tip, payload)
        event = {
            "schema": 1, "sequence": next_sequence,
            "previous": self._last_tip, "payload": payload, "hash": tip,
        }
        self.events.append({
            "id": next_sequence, "body": MARKER + _canonical(event),
            "user": {"login": ACTOR},
        })
        self._last_sequence = next_sequence
        self._last_tip = tip

    def checkpoint(self):
        return JournalCheckpoint(
            sequence=self._last_sequence, tip=self._last_tip,
            anchor_ref="INTEGRATION_TEST_ONLY_NO_INDEPENDENCE",
        )

    def get(self, path, *, query=None):
        if path == "/git/ref/heads/main":
            return {"ref": "refs/heads/main", "object": {"sha": self.main}}
        if path == "/contents/" + POLICY_PATH:
            assert query == {"ref": MAIN_SHA}
            return blob(json.dumps(self.policy).encode(), POLICY_PATH)
        if path == "/contents/" + REFERENCE_PATH:
            assert query == {"ref": MAIN_SHA}
            return blob(self.yaml, REFERENCE_PATH)
        if path == "/issues/236/comments":
            assert query["per_page"] == "100"
            return list(self.events)
        if path == "/git/ref/heads/" + BRANCH:
            if self.branch is None:
                raise ApiError("branch not found", status=404)
            return {"ref": "refs/heads/" + BRANCH, "object": {"sha": self.branch}}
        if path == "/contents/" + PATH:
            assert query == {"ref": BRANCH}
            if self.file is None:
                raise ApiError("file not found", status=404)
            return blob(self.file, PATH)
        if path == "/commits/" + PR_SHA:
            return {
                "sha": PR_SHA,
                "parents": [{"sha": self.created_commit_parent}],
                "files": self.created_commit_files,
            }
        if path == "/pulls":
            assert query["head"] == "HyungseonSong-plasma:" + BRANCH
            assert query["base"] == "main"
            return [] if self.pr is None else [self.pr]
        if path == "/pulls/99":
            return self.pr
        raise AssertionError("unexpected GitHub GET route " + path)

    def request(self, method, path, *, payload=None):
        self.writes.append((method, path))
        if method == "POST" and path == "/git/refs":
            assert self.branch is None
            self.branch = MAIN_SHA
            return {"ref": payload["ref"], "object": {"sha": MAIN_SHA}}
        if method == "PUT" and path == "/contents/" + PATH:
            assert payload["branch"] == BRANCH
            self.file = base64.b64decode(payload["content"])
            self.branch = PR_SHA
            return {"commit": {"sha": PR_SHA}}
        if method == "POST" and path == "/pulls":
            assert payload["draft"] is True
            self.pr = {
                "number": 99, "draft": True, "state": "open",
                "merged": False,
                "head": {"ref": BRANCH, "sha": self.branch},
                "base": {"ref": "main", "sha": MAIN_SHA},
                "html_url": "https://github.com/" + REPO + "/pull/99",
            }
            return {"number": 99}
        raise AssertionError("unexpected mutation attempted")


def service(api, *, checkpoint_reader=None, authority_verifier=None,
            grant_reader=None, grant_verifier=None, grant_reserver=None):
    """Test-only host wiring with fake owner identity and atomic ledger."""
    now = datetime.now(timezone.utc)
    grant = OperatorDelegationGrant(
        grant_id="operator-254-integration",
        operator_login=OPERATOR_LOGIN, delegate_id=DELEGATE_ID,
        repository=REPO, work_id=WORK_ID, action=ACTION,
        branch=BRANCH, target_path=PATH, expected_main_sha=MAIN_SHA,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        evidence_ref="TEST_ONLY_OWNER_AUTHENTICATION",
    )
    consumed = set()

    def reserve(value):
        if value.grant_id in consumed:
            return False
        consumed.add(value.grant_id)
        return True

    config = HostOwnedTrustConfig(
        journal_issue_number=ISSUE,
        trusted_journal_actor=ACTOR,
        independent_checkpoint_reader=(
            checkpoint_reader if checkpoint_reader is not None
            else api.checkpoint
        ),
        policy_authority_verifier=(
            authority_verifier if authority_verifier is not None
            else lambda _: False
        ),
        operator_grant_reader=(
            grant_reader if grant_reader is not None else lambda: grant
        ),
        operator_grant_verifier=(
            grant_verifier if grant_verifier is not None else lambda _: True
        ),
        operator_grant_reserver=(
            grant_reserver if grant_reserver is not None else reserve
        ),
    )
    return connect_hosted_dea_workflow_authoring(
        github_transport=api, host_config=config
    )


class HostedDeaAuthoringIntegrationTests(unittest.TestCase):
    def test_real_internal_components_allow_only_scoped_draft_api(self):
        api = FakeGitHubTransport()
        runner = service(api)
        self.assertFalse(hasattr(runner, "merge"))
        self.assertFalse(hasattr(runner, "dispatch"))
        result = runner.create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(result.pr_number, 99)
        self.assertTrue(result.draft)
        self.assertFalse(result.merged)
        self.assertFalse(result.executable_authority)
        self.assertEqual(
            api.writes,
            [
                ("POST", "/git/refs"),
                ("PUT", "/contents/" + PATH),
                ("POST", "/pulls"),
            ],
        )

    def test_hosted_broker_rejects_unscoped_commit_before_pr(self):
        api = FakeGitHubTransport()
        api.created_commit_files.append({
            "filename": "src/extra.py", "status": "modified",
        })
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "CREATED_COMMIT_SCOPE_MISMATCH"
        ):
            service(api).create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(
            api.writes,
            [("POST", "/git/refs"), ("PUT", "/contents/" + PATH)],
        )
        self.assertIsNone(api.pr)

    def test_unverified_delegation_blocks_hosted_writes(self):
        api = FakeGitHubTransport()
        with self.assertRaisesRegex(
            OperatorDelegationError, "DELEGATION_NOT_AUTHENTIC_OR_REVOKED"
        ):
            service(
                api, grant_verifier=lambda _: False
            ).create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(api.writes, [])

    def test_missing_delegation_rejected_by_host(self):
        api = FakeGitHubTransport()
        with self.assertRaisesRegex(
            OperatorDelegationError, "TYPED_DELEGATION_REQUIRED"
        ):
            service(
                api, grant_reader=lambda: None
            ).create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(api.writes, [])

    def test_nonatomic_or_unavailable_reservation_blocks_hosted_writes(self):
        api = FakeGitHubTransport()
        with self.assertRaisesRegex(
            OperatorDelegationError, "DELEGATION_ALREADY_USED_OR_NOT_RESERVED"
        ):
            service(
                api, grant_reserver=lambda _: False
            ).create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(api.writes, [])

    def test_unadopted_policy_refuses_before_writes(self):
        api = FakeGitHubTransport(policy=DEFAULT_POLICY)
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "EXACT_PATH_POLICY_NOT_ADOPTED"
        ):
            service(api).create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(api.writes, [])

    def test_wrong_trusted_main_sha_fails_without_writes(self):
        api = FakeGitHubTransport()
        with self.assertRaisesRegex(WorkflowAuthoringError, "MAIN_HEAD_CHANGED"):
            service(api).create_review_only_draft(expected_main_sha="c"*40)
        self.assertEqual(api.writes, [])

    def test_wrong_checkpoint_tip_stops_before_any_writes(self):
        api = FakeGitHubTransport()
        bad = JournalCheckpoint(
            sequence=1, tip="f"*64, anchor_ref="different-boundary",
        )
        with self.assertRaises(BlockerGateError):
            service(api, checkpoint_reader=lambda: bad).create_review_only_draft(
                expected_main_sha=MAIN_SHA
            )
        self.assertEqual(api.writes, [])

    def test_active_policy_blocker_cannot_be_ignored(self):
        api = FakeGitHubTransport()
        api.register_event({
            "event": "BLOCKED",
            "intent": logical_intent_id(
                repository=REPO, branch=BRANCH, work_id=WORK_ID,
                paths=(PATH,)
            ),
            "source": "repository_policy", "provider": "github-connector",
            "evidence_ref": "prior-denial-001", "http_status": None,
        })
        with self.assertRaisesRegex(BlockerGateError, "ACTIVE_BLOCKER"):
            service(api).create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(api.writes, [])

    def test_missing_journal_registration_denied(self):
        api = FakeGitHubTransport()
        api.events.clear()
        api._last_sequence = 0
        api._last_tip = ZERO
        api.register_event({
            "event": "REGISTERED",
            "intent": "f"*64, "head": MAIN_SHA,
            "evidence_ref": "unrelated-task",
        })
        with self.assertRaisesRegex(BlockerGateError, "WORK_REGISTRATION"):
            service(api).create_review_only_draft(expected_main_sha=MAIN_SHA)
        self.assertEqual(api.writes, [])

    def test_invalid_host_config_is_rejected(self):
        api = FakeGitHubTransport()
        for number in (0, -1, True):
            with self.subTest(number=number), self.assertRaisesRegex(
                WorkflowAuthoringError, "HOST_TRUST_CONFIG_INVALID"
            ):
                connect_hosted_dea_workflow_authoring(
                    github_transport=api,
                    host_config=HostOwnedTrustConfig(
                        journal_issue_number=number,
                        trusted_journal_actor=ACTOR,
                        independent_checkpoint_reader=api.checkpoint,
                        policy_authority_verifier=lambda _: False,
                        operator_grant_reader=lambda: None,
                        operator_grant_verifier=lambda _: False,
                        operator_grant_reserver=lambda _: False,
                    ),
                )
        self.assertEqual(api.writes, [])

    def test_mismatched_host_repository_denied(self):
        api = FakeGitHubTransport()
        api.repository = "someone/else"
        with self.assertRaisesRegex(
            WorkflowAuthoringError, "HOST_GITHUB_REPOSITORY_MISMATCH"
        ):
            service(api)
        self.assertEqual(api.writes, [])


if __name__ == "__main__":
    unittest.main()
