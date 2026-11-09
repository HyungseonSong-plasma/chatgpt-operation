"""Simulated durable-ACK/SIGKILL/20-Child cases for Draft-only executor.

All tests run against a fake GitHub REST port. These are NOT live
GitHub Actions/20-agent qualifications and DO NOT grant execution authority.
"""
from __future__ import annotations

import copy
import hashlib
import unittest

from chatgpt_operation.controller.agent_issue_provision import (
    create_provision, initial_child_body,
)
from chatgpt_operation.controller.agent_issue_durable_executor import (
    INTENT_MARKER, DurableChildError, advance_durable_child,
)

REPO = "HyungseonSong-plasma/chatgpt-operation"
AUTHOR = "github-actions[bot]"
BASE = "https://api.github.com/repos/" + REPO + "/issues/"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def spec(n=0, *, changed=False):
    return create_provision(
        repository=REPO, parent_issue=400, agent_id=f"agent-{n:03}",
        work_id="issue:400",
        plan_sha256=sha("approved-plan"), policy_sha256=sha("approved-policy"),
        source_head_sha="a" * 40,
        units=[{
            "id": "scan-0",
            "input_sha256": sha(f"unit-{n}-{'changed' if changed else 'stable'}"),
            "requires": [], "gates": ["evidence"],
        }],
    )


class FakeGitHub:
    """One serialized repository-native Bootstrap writer; no live GitHub use."""

    def __init__(self):
        self.issues = {
            400: {
                "number": 400, "id": 4400, "url": BASE + "400",
                "state": "open", "labels": ["samuel"],
                "body": "untouched canonical parent",
            },
        }
        self.comments = {400: []}
        self.links = {400: []}
        self.next_issue = 500
        self.next_comment = 100
        self.calls = []
        self.fail_before = set()
        self.lose_ack = set()
        self.sigkill_on = set()

    def get(self, path, *, query=None):
        self.calls.append(("GET", path))
        if path == "/issues":
            if query is None or query.get("state") != "all":
                raise AssertionError("must enumerate full Issue inventory")
            result = list(self.issues.values())
        elif path.startswith("/issues/") and path.endswith("/comments"):
            n = int(path.split("/")[2])
            result = self.comments.get(n, [])
        elif path.startswith("/issues/") and path.endswith("/sub_issues"):
            n = int(path.split("/")[2])
            result = [self.issues[i] for i in self.links.get(n, [])]
        elif path.startswith("/issues/") and path.count("/") == 2:
            return copy.deepcopy(self.issues[int(path.split("/")[2])])
        else:
            raise AssertionError("unexpected native read " + path)
        if query is None or int(query["per_page"]) != 100:
            raise AssertionError("unbounded native inventory")
        page = int(query["page"])
        return copy.deepcopy(result[(page-1)*100:page*100])

    def request(self, method, path, *, payload=None):
        self.calls.append((method, path))
        key = method + path
        if key in self.fail_before:
            self.fail_before.remove(key)
            raise TimeoutError("did not reach GitHub")
        if method == "POST" and path == "/issues":
            n = self.next_issue
            self.next_issue += 1
            obj = {
                "id": 10_000 + n, "number": n, "url": BASE + str(n),
                "state": "open", "body": payload["body"],
                "labels": payload["labels"],
            }
            self.issues[n] = obj
            self.comments[n] = []
            response = (201, copy.deepcopy(obj))
        elif method == "PATCH" and path.startswith("/issues/"):
            n = int(path.split("/")[2])
            self.issues[n]["body"] = payload["body"]
            response = (200, copy.deepcopy(self.issues[n]))
        elif method == "POST" and path == "/issues/400/sub_issues":
            child = next(
                n for n, v in self.issues.items()
                if v["id"] == payload["sub_issue_id"]
            )
            if child not in self.links[400]:
                self.links[400].append(child)
            response = (201, copy.deepcopy(self.issues[child]))
        elif method == "POST" and path == "/issues/400/comments":
            self.next_comment += 1
            value = {
                "id": self.next_comment, "body": payload["body"],
                "user": {"login": AUTHOR},
                "created_at": "2026-11-09T00:00:00Z",
                "updated_at": "2026-11-09T00:00:00Z",
            }
            self.comments[400].append(value)
            response = (201, copy.deepcopy(value))
        else:
            raise AssertionError("unapproved test mutation " + key)
        if key in self.sigkill_on:
            self.sigkill_on.remove(key)
            raise SystemExit("simulated abrupt process termination")
        if key in self.lose_ack:
            self.lose_ack.remove(key)
            raise TimeoutError("mutation persisted, ACK lost")
        return response


def advance(gh, s):
    return advance_durable_child(
        gh, s, parent_issue=copy.deepcopy(gh.issues[400]),
        trusted_author=AUTHOR,
    )


def complete(gh, s):
    trace = []
    for _ in range(6):
        result = advance(gh, s)
        trace.append(result["status"])
        if result["status"] == "READY":
            return trace
        if result["status"] != "OBSERVED_ADVANCE":
            raise AssertionError("unexpected nonterminal status: " + repr(result))
    raise AssertionError("provisioning did not complete")


class DurableChildExecutorTests(unittest.TestCase):
    def test_serialized_child_fully_observed_four_stages(self):
        gh = FakeGitHub()
        trace = complete(gh, spec())
        self.assertEqual(trace, ["OBSERVED_ADVANCE"] * 4 + ["READY"])
        self.assertEqual(gh.links[400], [500])
        self.assertEqual(len(gh.comments[400]), 5)
        self.assertEqual(
            sum(INTENT_MARKER in x["body"] for x in gh.comments[400]), 4,
        )
        self.assertEqual(gh.issues[400]["body"], "untouched canonical parent")
        self.assertNotIn(("PATCH", "/issues/400"), gh.calls)

    def test_twenty_agents_replay_without_duplicate_issue_or_link(self):
        gh = FakeGitHub()
        for i in range(20):
            self.assertEqual(complete(gh, spec(i))[-1], "READY")
        for i in range(20):
            self.assertEqual(advance(gh, spec(i))["status"], "READY")
        self.assertEqual(gh.next_issue, 520)
        self.assertEqual(len(gh.links[400]), 20)
        self.assertEqual(len(set(gh.links[400])), 20)
        self.assertEqual(gh.next_comment - 100, 100)
        self.assertEqual(
            sum(x == ("POST", "/issues") for x in gh.calls), 20,
        )

    def test_lost_create_ack_reconciles_observed_issue_only(self):
        gh = FakeGitHub()
        gh.lose_ack.add("POST/issues")
        self.assertEqual(
            advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_ACK",
        )
        self.assertIn(500, gh.issues)
        self.assertEqual(complete(gh, spec())[-1], "READY")
        self.assertEqual(sum(x == ("POST", "/issues") for x in gh.calls), 1)

    def test_pre_create_transport_failure_does_not_retry_unsafe_post(self):
        gh = FakeGitHub()
        gh.fail_before.add("POST/issues")
        self.assertEqual(
            advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_ACK",
        )
        self.assertEqual(
            advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_ACK",
        )
        self.assertNotIn(500, gh.issues)
        self.assertEqual(sum(x == ("POST", "/issues") for x in gh.calls), 1)

    def test_lost_intent_ack_blocks_without_creating_any_child(self):
        gh = FakeGitHub()
        gh.lose_ack.add("POST/issues/400/comments")
        self.assertEqual(
            advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_INTENT",
        )
        self.assertEqual(advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_ACK")
        self.assertNotIn(500, gh.issues)
        self.assertFalse(any(x == ("POST", "/issues") for x in gh.calls))

    def test_abrupt_process_exit_after_intent_is_safe_on_resume(self):
        gh = FakeGitHub()
        gh.sigkill_on.add("POST/issues/400/comments")
        with self.assertRaises(SystemExit):
            advance(gh, spec())
        self.assertEqual(
            advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_ACK",
        )
        self.assertEqual(sum(x == ("POST", "/issues") for x in gh.calls), 0)

    def test_lost_ack_finalize_link_and_parent_registration(self):
        for method, path in (
            ("PATCH", "/issues/500"),
            ("POST", "/issues/400/sub_issues"),
            ("POST", "/issues/400/comments"),
        ):
            gh = FakeGitHub()
            # The comment path is also the initial durable intent write, so
            # inject only once the prior operations have completed.
            for _ in range({
                ("PATCH", "/issues/500"): 1,
                ("POST", "/issues/400/sub_issues"): 2,
                ("POST", "/issues/400/comments"): 3,
            }[(method, path)]):
                self.assertEqual(advance(gh, spec())["status"], "OBSERVED_ADVANCE")
            if path.endswith("/comments"):
                # the next write would be another intent; lose its ACK, then
                # fail closed with an observed but unexecuted intent.
                gh.lose_ack.add(method + path)
                self.assertEqual(
                    advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_INTENT",
                )
                self.assertEqual(
                    advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_ACK",
                )
            else:
                gh.lose_ack.add(method + path)
                self.assertEqual(
                    advance(gh, spec())["status"], "BLOCKED_UNCERTAIN_ACK",
                )
                self.assertEqual(complete(gh, spec())[-1], "READY")
                self.assertEqual(
                    sum(x == (method, path) for x in gh.calls), 1,
                )

    def test_tampered_immutable_intent_is_rejected(self):
        gh = FakeGitHub()
        self.assertEqual(advance(gh, spec())["status"], "OBSERVED_ADVANCE")
        gh.comments[400][0]["updated_at"] = "2026-11-09T00:01:00Z"
        with self.assertRaisesRegex(DurableChildError, "edited Child intent"):
            advance(gh, spec())

    def test_changed_agent_plan_cannot_reuse_prior_intent(self):
        gh = FakeGitHub()
        advance(gh, spec())
        with self.assertRaisesRegex(DurableChildError, "conflicting Child intent"):
            advance(gh, spec(changed=True))

    def test_duplicate_intent_blocks(self):
        gh = FakeGitHub()
        advance(gh, spec())
        gh.comments[400].append({
            **copy.deepcopy(gh.comments[400][0]), "id": 999,
        })
        with self.assertRaisesRegex(DurableChildError, "duplicate Child"):
            advance(gh, spec())

    def test_missing_samuel_label_denies_any_write(self):
        gh = FakeGitHub()
        gh.issues[400]["labels"] = []
        with self.assertRaisesRegex(DurableChildError, "parent live Issue"):
            advance(gh, spec())
        self.assertFalse(any(m != "GET" for m, _ in gh.calls))


if __name__ == "__main__":
    unittest.main()
