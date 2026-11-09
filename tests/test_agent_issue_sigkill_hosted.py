"""Real subprocess SIGKILL and durable simulated GitHub API state recovery.

These tests actually send SIGKILL to a child controller process in CI,
but API calls are a local durable GitHub REST simulator. They do NOT
prove killing an actual remote GitHub Actions job during network writes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from chatgpt_operation.controller.agent_issue_durable_executor import (
    advance_durable_child, INTENT_MARKER,
)
from chatgpt_operation.controller.agent_issue_provision import create_provision

REPO = "HyungseonSong-plasma/chatgpt-operation"
URL = "https://api.github.com/repos/" + REPO + "/issues/"
AUTHOR = "github-actions[bot]"


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def provision():
    return create_provision(
        repository=REPO, parent_issue=400,
        agent_id="agent-sigkill", work_id="issue:400",
        plan_sha256=digest("approved-plan"),
        policy_sha256=digest("approved-policy"),
        source_head_sha="a" * 40,
        units=[{
            "id": "scan-0", "input_sha256": digest("input"),
            "requires": [], "gates": ["evidence"],
        }],
    )


class DurableFakeGitHub:
    """Persist every observed server mutation to an atomic local JSON file."""

    def __init__(self, path, *, kill_after=None):
        self.path = Path(path)
        self.kill_after = kill_after

    def initialize(self):
        state = {
            "issues": {
                "400": {
                    "number": 400, "id": 4400, "url": URL + "400",
                    "state": "open", "labels": ["samuel"],
                    "body": "immutable task parent",
                },
            },
            "comments": {"400": []},
            "links": {"400": []},
            "next_issue": 500, "next_comment": 100,
            "events": [],
        }
        self._save(state)

    def _load(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, state):
        tmp = self.path.with_suffix(".pending")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def get(self, path, *, query=None):
        state = self._load()
        if path == "/issues":
            assert query is not None and query["state"] == "all"
            values = list(state["issues"].values())
        elif path.startswith("/issues/") and path.count("/") == 2:
            return copy.deepcopy(state["issues"][path.rsplit("/", 1)[-1]])
        elif path.startswith("/issues/") and path.endswith("/comments"):
            parent = path.split("/")[2]
            values = state["comments"].get(parent, [])
        elif path.startswith("/issues/") and path.endswith("/sub_issues"):
            parent = path.split("/")[2]
            values = [state["issues"][str(i)] for i in state["links"].get(parent, [])]
        else:
            raise AssertionError("unapproved fake GitHub GET " + path)
        assert query and query["per_page"] == "100"
        page = int(query["page"])
        return copy.deepcopy(values[(page-1)*100:page*100])

    def request(self, method, path, *, payload=None):
        state = self._load()
        key = method + path
        state["events"].append(key)
        if method == "POST" and path == "/issues":
            n = state["next_issue"]
            state["next_issue"] += 1
            issue = {
                "number": n, "id": 10_000 + n,
                "url": URL + str(n), "state": "open",
                "labels": payload["labels"], "body": payload["body"],
            }
            state["issues"][str(n)] = issue
            state["comments"][str(n)] = []
            answer = (201, copy.deepcopy(issue))
        elif method == "PATCH" and path.startswith("/issues/"):
            n = path.split("/")[2]
            state["issues"][n]["body"] = payload["body"]
            answer = (200, copy.deepcopy(state["issues"][n]))
        elif method == "POST" and path == "/issues/400/sub_issues":
            child = next(
                x for x in state["issues"].values()
                if x["id"] == payload["sub_issue_id"]
            )
            number = child["number"]
            if number not in state["links"]["400"]:
                state["links"]["400"].append(number)
            answer = (201, copy.deepcopy(child))
        elif method == "POST" and path == "/issues/400/comments":
            state["next_comment"] += 1
            comment = {
                "id": state["next_comment"], "body": payload["body"],
                "user": {"login": AUTHOR},
                "created_at": "2026-11-09T00:00:00Z",
                "updated_at": "2026-11-09T00:00:00Z",
            }
            state["comments"]["400"].append(comment)
            answer = (201, copy.deepcopy(comment))
        else:
            raise AssertionError("unapproved fake mutation " + key)
        self._save(state)
        if self.kill_after == key:
            os.kill(os.getpid(), signal.SIGKILL)
            raise AssertionError("SIGKILL did not terminate process")
        return answer


def advance(fake):
    return advance_durable_child(
        fake, provision(),
        parent_issue=fake.get("/issues/400"),
        trusted_author=AUTHOR,
    )


def worker(path, kill_after):
    fake = DurableFakeGitHub(path, kill_after=kill_after)
    advance(fake)
    raise AssertionError("injected SIGKILL was not reached")


class HostedRealSigkillTests(unittest.TestCase):
    def killed_child(self, path, kill_after):
        env = dict(os.environ)
        # This subprocess must use the tested source tree, never a pinned
        # production credential, workflow or external repository write.
        task = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "--worker", str(path), kill_after],
            capture_output=True, text=True, timeout=20,
            env=env,
        )
        self.assertEqual(task.returncode, -signal.SIGKILL, task.stderr)

    def test_real_sigkill_after_durable_intent_prevents_unsafe_create_retry(self):
        if os.name != "posix":
            self.skipTest("POSIX-only SIGKILL qualification")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "github.json"
            github = DurableFakeGitHub(path)
            github.initialize()
            self.killed_child(path, "POST/issues/400/comments")
            state = github._load()
            self.assertEqual(len(state["comments"]["400"]), 1)
            self.assertTrue(state["comments"]["400"][0]["body"].startswith(INTENT_MARKER))
            self.assertNotIn("500", state["issues"])

            # A fresh process has no volatile memory of the previous call.
            outcome = advance(DurableFakeGitHub(path))
            self.assertEqual(outcome["status"], "BLOCKED_UNCERTAIN_ACK")
            state = github._load()
            self.assertEqual(state["events"].count("POST/issues"), 0)
            self.assertEqual(len(state["comments"]["400"]), 1)

    def test_real_sigkill_after_child_create_recovers_by_remote_readback(self):
        if os.name != "posix":
            self.skipTest("POSIX-only SIGKILL qualification")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "github.json"
            github = DurableFakeGitHub(path)
            github.initialize()
            self.killed_child(path, "POST/issues")
            state = github._load()
            self.assertIn("500", state["issues"])
            self.assertEqual(state["events"].count("POST/issues"), 1)
            self.assertEqual(len(state["comments"]["400"]), 1)

            steps = []
            for _ in range(5):
                outcome = advance(DurableFakeGitHub(path))
                steps.append(outcome["status"])
                if outcome["status"] == "READY":
                    break
            state = github._load()
            self.assertEqual(steps, ["OBSERVED_ADVANCE"] * 3 + ["READY"])
            self.assertEqual(state["events"].count("POST/issues"), 1)
            self.assertEqual(state["links"]["400"], [500])
            self.assertEqual(len(state["comments"]["400"]), 5)
            self.assertEqual(state["issues"]["400"]["body"],
                             "immutable task parent")


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--worker":
    worker(sys.argv[2], sys.argv[3])
elif __name__ == "__main__":
    unittest.main()
