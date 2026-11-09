"""Isolated one-shot native GitHub Sub-issue qualification (non-Samuel work).

Do not reuse with a different Parent. This script is activated exclusively
by the branch-scoped workflow, never by the Samuel scheduled Controller.
It performs only two allowed native Sub-issue link POSTs and GitHub readback.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

REPO = "HyungseonSong-plasma/chatgpt-operation"
BRANCH = "samuel/live-child-qualification-282-v01"
PARENT = (282, 6289580624, "[qualification sandbox] Agent Child crash/ACK live parent (non-admitted)")
CHILDREN = {
    283: (6289591915, "[qualification sandbox] Child Alpha — isolated Parent #282",
          "<!-- samuel-live-sandbox-child-alpha-v02 -->"),
    284: (6289592486, "[qualification sandbox] Child Beta — isolated Parent #282",
          "<!-- samuel-live-sandbox-child-beta-v02 -->"),
}


def api(path: str, *, method: str = "GET", fields: dict[str, int] | None = None):
    command = [
        "gh", "api", "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
    ]
    if method != "GET":
        command.extend(["--method", method])
    for key, value in (fields or {}).items():
        command.extend(["-F", f"{key}={value}"])
    command.append(f"repos/{REPO}{path}")
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        # Error details may include host metadata; never include token.
        raise RuntimeError(f"native GitHub REST {method} failed (exit {result.returncode})")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("native REST returned non-JSON body") from exc


def issue(number: int, expected_id: int, title: str, marker: str) -> dict:
    obj = api(f"/issues/{number}")
    if (
        not isinstance(obj, dict)
        or obj.get("number") != number
        or obj.get("id") != expected_id
        or obj.get("title") != title
        or obj.get("state") != "open"
        or obj.get("labels")
        or "pull_request" in obj
        or not isinstance(obj.get("body"), str)
        or not obj["body"].startswith(marker)
    ):
        raise RuntimeError("sandbox Issue identity or non-admission condition changed")
    return obj


def linked() -> list[dict]:
    value = api("/issues/282/sub_issues?per_page=100&page=1")
    if not isinstance(value, list):
        raise RuntimeError("sandbox native Sub-issue listing malformed")
    allowed = {x[0] for x in CHILDREN.values()}
    numbers = {283, 284}
    if (
        len(value) != len({x.get("id") for x in value})
        or any(not isinstance(x, dict) or x.get("id") not in allowed
               or x.get("number") not in numbers for x in value)
    ):
        raise RuntimeError("sandbox Sub-issue inventory contains foreign links")
    return value


def main() -> int:
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPO
        or os.environ.get("GITHUB_REF") != f"refs/heads/{BRANCH}"
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or not os.environ.get("GITHUB_TOKEN")
        or not os.environ.get("GITHUB_SHA")
    ):
        raise RuntimeError("noncanonical live qualification invocation")
    issue(PARENT[0], PARENT[1], PARENT[2],
          "<!-- samuel-agent-child-live-sandbox-v02 -->")
    for number, (internal_id, title, marker) in CHILDREN.items():
        issue(number, internal_id, title, marker)
    before = linked()
    created = []
    for number, (internal_id, _, _) in CHILDREN.items():
        if any(row["id"] == internal_id for row in linked()):
            continue
        # Only the sandbox Parent may be linked; children must already exist.
        # Discard the response at the caller layer to simulate lost ACK.
        api("/issues/282/sub_issues", method="POST",
            fields={"sub_issue_id": internal_id})
        created.append(number)
        confirmed = False
        for _ in range(8):
            if any(row["id"] == internal_id for row in linked()):
                confirmed = True
                break
            time.sleep(1)
        if not confirmed:
            raise RuntimeError("unknown ACK; refusing duplicate native link POST")
    final = linked()
    if {row["id"] for row in final} != {v[0] for v in CHILDREN.values()}:
        raise RuntimeError("native Sub-issue forward relation differs")
    for number in CHILDREN:
        parent = api(f"/issues/{number}/parent")
        if not isinstance(parent, dict) or parent.get("id") != PARENT[1]:
            raise RuntimeError("native reverse parent relation mismatch")
    # All source Issues must remain unlabelled, with immutable identities.
    issue(PARENT[0], PARENT[1], PARENT[2],
          "<!-- samuel-agent-child-live-sandbox-v02 -->")
    for number, (internal_id, title, marker) in CHILDREN.items():
        issue(number, internal_id, title, marker)
    print(json.dumps({
        "status": "PASS",
        "parent": PARENT[0],
        "native_child_numbers": sorted(CHILDREN),
        "links_before": len(before),
        "links_after": len(final),
        "created_native_links": sorted(created),
        "idempotent_skips": len(CHILDREN) - len(created),
        "work_admission": False,
        "parent_state_patch": False,
        "live_issue_creation_proven": False,
        "ack_loss": "caller_discarded_link_POST_response_only",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print("NATIVE_SANDBOX_282=BLOCKED_SCOPE " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
