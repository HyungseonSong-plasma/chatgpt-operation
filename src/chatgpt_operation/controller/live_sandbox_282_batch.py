"""Bounded live GitHub Child-create / native-link qualification, sandbox #282.

This is NOT the production Samuel Controller. Only the branch-restricted
GitHub Actions job may invoke it. Every writable object is restricted to
the separate non-admitted #282 sandbox. Uncertain GitHub acknowledgments
must never lead to a speculative duplicate CREATE.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from typing import Any

REPO = "HyungseonSong-plasma/chatgpt-operation"
BRANCH = "samuel/live-child-qualification-282-v01"
ROOT = f"repos/{REPO}"
PARENT = 282
PARENT_ID = 6289580624
TRIAL = "samuel-live-282-20-v01"
COUNT = 20
MAX_NEW = 5
AUTHOR = "github-actions[bot]"
LINKS_EXISTING = {6289591915, 6289592486}
PREFIX = "<!-- samuel-live-282-"
EXPECTED_PARENT_TITLE = "[qualification sandbox] Agent Child crash/ACK live parent (non-admitted)"


def api(path: str, *, method: str = "GET",
        payload: dict[str, Any] | None = None) -> Any:
    allowed_get = (
        path.startswith("/issues?state=all&per_page=100&page=")
        or path.startswith("/issues/282/comments?per_page=100&page=")
        or path in {"/issues/282", "/issues/282/sub_issues?per_page=100&page=1"}
        or path.startswith("/issues/") and path.endswith("/parent")
    )
    allowed_post = path in {
        "/issues", "/issues/282/comments", "/issues/282/sub_issues",
    }
    if not ((method == "GET" and allowed_get) or
            (method == "POST" and allowed_post)):
        raise RuntimeError("GitHub REST path or verb is not in sandbox allowlist")
    command = [
        "gh", "api", "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
    ]
    if method == "POST":
        command += ["--method", "POST", "--input", "-"]
    command.append(ROOT + path)
    p = subprocess.run(
        command, input=json.dumps(payload, sort_keys=True) if payload else None,
        capture_output=True, text=True, timeout=35,
    )
    if p.returncode != 0:
        # Never echo stderr from privileged GitHub tokens.
        raise RuntimeError(f"GitHub {method} returned exit {p.returncode}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub REST response is not parseable JSON") from exc


def require_event():
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPO
        or os.environ.get("GITHUB_REF") != f"refs/heads/{BRANCH}"
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or not os.environ.get("GITHUB_TOKEN")
        or not os.environ.get("GITHUB_SHA")
    ):
        raise RuntimeError("noncanonical live sandbox run identity")


def parent():
    x = api("/issues/282")
    if (
        not isinstance(x, dict)
        or x.get("number") != PARENT
        or x.get("id") != PARENT_ID
        or x.get("title") != EXPECTED_PARENT_TITLE
        or x.get("state") != "open"
        or x.get("labels")
        or not isinstance(x.get("body"), str)
        or not x["body"].startswith("<!-- samuel-agent-child-live-sandbox-v02 -->")
    ):
        raise RuntimeError("Sandbox Parent #282 is not the exact non-admitted Parent")
    return x


def pages(root: str, *, maximum: int = 20) -> list[dict]:
    output: list[dict] = []
    ids: set[int] = set()
    for page in range(1, maximum + 1):
        value = api(f"{root}&page={page}")
        if not isinstance(value, list) or len(value) > 100:
            raise RuntimeError("native GitHub inventory cannot be trusted")
        for row in value:
            if (
                not isinstance(row, dict) or type(row.get("id")) is not int
                or row["id"] in ids
            ):
                raise RuntimeError("duplicate/missing GitHub inventory identity")
            ids.add(row["id"])
            output.append(row)
        if len(value) < 100:
            return output
    raise RuntimeError("GitHub Issue inventory is truncated")


def all_issues():
    # Native listing is briefly eventually consistent following a real
    # CREATE; unrelated Issue activity also changes timestamps. Compare
    # only the complete, security-relevant sandbox projection, retrying
    # boundedly WITHOUT performing a second Issue POST.
    for _ in range(10):
        first = pages("/issues?state=all&per_page=100")
        second = pages("/issues?state=all&per_page=100")
        target = lambda rows: [
            {key: item.get(key) for key in (
                "id", "number", "state", "title", "body", "labels", "url",
            )}
            for item in rows
            if isinstance(item.get("body"), str)
            and item["body"].startswith("<!-- samuel-live-282-child-v01:")
        ]
        a, b = target(first), target(second)
        if a == b:
            return second
        time.sleep(1)
    raise RuntimeError("GitHub sandbox Issue inventory did not converge")


def comments():
    first = pages("/issues/282/comments?per_page=100", maximum=10)
    second = pages("/issues/282/comments?per_page=100", maximum=10)
    if first != second:
        raise RuntimeError("Parent comment inventory changed during readback")
    return second


def marker(stage: str, agent: int) -> str:
    return f"<!-- samuel-live-282-{stage}-v01:agent-{agent:03d} -->"


def note(stage: str, agent: int, **extra) -> str:
    obj = {
        "schema_version": 1, "trial_id": TRIAL,
        "parent_issue": PARENT, "agent_id": f"agent-{agent:03d}",
        "stage": stage, **extra,
    }
    return marker(stage, agent) + "\n~~~json\n" + json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
    ) + "\n~~~"


def existing_comment(stage: str, agent: int):
    matches = [
        x for x in comments()
        if isinstance(x.get("body"), str) and
        x["body"].startswith(marker(stage, agent))
    ]
    if len(matches) > 1:
        raise RuntimeError("duplicate immutable Parent stage comment")
    if not matches:
        return None
    row = matches[0]
    if (
        row.get("user", {}).get("login") != AUTHOR
        or row.get("created_at") != row.get("updated_at")
        or not isinstance(row.get("body"), str)
    ):
        raise RuntimeError("untrusted or edited Parent stage comment")
    return row


def append_comment(stage: str, agent: int, **extra):
    if existing_comment(stage, agent):
        return False
    body = note(stage, agent, **extra)
    api("/issues/282/comments", method="POST", payload={"body": body})
    observed = existing_comment(stage, agent)
    if observed is None or observed.get("body") != body:
        raise RuntimeError("unconfirmed GitHub Parent stage record")
    time.sleep(0.25)
    return True


def child_body(agent: int):
    obj = {
        "schema_version": 1, "trial_id": TRIAL,
        "parent_issue": PARENT, "agent_id": f"agent-{agent:03d}",
        "work_id": f"sandbox:{TRIAL}",
        "candidate_revision": "draft-only", "production_admission": False,
    }
    return marker("child", agent) + "\n~~~json\n" + json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
    ) + "\n~~~"


def child_title(agent: int):
    return f"[qualification sandbox #282] Agent unit {agent:03d} (non-admitted)"


def match_child(agent: int):
    body = child_body(agent)
    matches = [
        x for x in all_issues()
        if x.get("pull_request") is None and
        isinstance(x.get("body"), str) and
        x["body"].startswith(marker("child", agent))
    ]
    if len(matches) > 1:
        raise RuntimeError("duplicate Child logical allocation")
    if not matches:
        return None
    issue = matches[0]
    if (
        type(issue.get("number")) is not int or
        type(issue.get("id")) is not int or
        issue.get("title") != child_title(agent) or
        issue.get("body") != body or issue.get("state") != "open" or
        issue.get("labels") or
        issue.get("url") != f"https://api.github.com/repos/{REPO}/issues/{issue['number']}"
    ):
        raise RuntimeError("Child Issue identity or body has been changed")
    return issue


def native_links():
    result = api("/issues/282/sub_issues?per_page=100&page=1")
    if not isinstance(result, list) or len(result) != len({i.get("id") for i in result}):
        raise RuntimeError("native Sub-issue inventory is ambiguous")
    if any(type(i.get("id")) is not int for i in result):
        raise RuntimeError("malformed native Sub-issue identity")
    return result


def require_linked(issue):
    number = issue["number"]
    parent_obj = api(f"/issues/{number}/parent")
    if (
        not isinstance(parent_obj, dict)
        or parent_obj.get("id") != PARENT_ID
        or parent_obj.get("number") != PARENT
    ):
        raise RuntimeError("reverse native Parent relation missing")


def create_worker(agent: int):
    # This child process dies AFTER the actual GitHub API has persisted an
    # Issue and returned its response. The orchestration process survives.
    api("/issues", method="POST", payload={
        "title": child_title(agent), "body": child_body(agent),
        "labels": [],
    })
    os.kill(os.getpid(), signal.SIGKILL)
    raise RuntimeError("SIGKILL unexpectedly returned")


def ensure_created(agent: int):
    found = match_child(agent)
    intent = existing_comment("create-intent", agent)
    if found:
        if not intent:
            raise RuntimeError("existing Child lacks durable create intent")
        return found, False
    if intent:
        # A previous create may have committed but not yet appeared in a
        # readback. Do not repeat an uncertain Issue POST.
        raise RuntimeError("BLOCKED_UNCERTAIN_CREATE_ACK")
    append_comment("create-intent", agent, issue_body_sha256=hashlib.sha256(
        child_body(agent).encode("utf-8"),
    ).hexdigest())
    if agent == 1:
        child = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--sigkill-worker", str(agent)],
            capture_output=True, text=True, timeout=70,
        )
        if child.returncode != -signal.SIGKILL:
            raise RuntimeError("actual post-create worker SIGKILL not observed")
    else:
        # Agent #000 deliberately does not consume the Issue POST response:
        # a caller-layer dropped ACK followed by remote authoritative lookup.
        api("/issues", method="POST", payload={
            "title": child_title(agent), "body": child_body(agent), "labels": [],
        })
    # The GitHub list endpoint is eventually consistent immediately after
    # creating an Issue. Bound the read-after-write observation window;
    # NEVER issue a second CREATE while the ACK/visibility is uncertain.
    found = None
    for _ in range(12):
        time.sleep(1)
        found = match_child(agent)
        if found is not None:
            break
    if found is None:
        raise RuntimeError("CREATE status unknown; no blind retry permitted")
    return found, True


def ensure_link(agent: int, child: dict):
    linked = native_links()
    if any(x["id"] == child["id"] for x in linked):
        if not existing_comment("link-intent", agent):
            raise RuntimeError("Child native link lacks durable intent")
        require_linked(child)
        return False
    if existing_comment("link-intent", agent):
        raise RuntimeError("BLOCKED_UNCERTAIN_LINK_ACK")
    append_comment("link-intent", agent, internal_issue_id=child["id"])
    api("/issues/282/sub_issues", method="POST",
        payload={"sub_issue_id": child["id"]})
    if not any(x["id"] == child["id"] for x in native_links()):
        raise RuntimeError("native link not confirmed; no blind retry")
    require_linked(child)
    time.sleep(0.25)
    return True


def ensure_record(agent: int, child: dict):
    receipt = existing_comment("allocation", agent)
    body = note(
        "allocation", agent, child_issue=child["number"],
        child_internal_id=child["id"],
    )
    if receipt:
        if receipt.get("body") != body:
            raise RuntimeError("conflicting immutable Child allocation receipt")
        return False
    append_comment(
        "allocation", agent, child_issue=child["number"],
        child_internal_id=child["id"],
    )
    return True


def audit_all():
    # One stable, complete snapshot is sufficient for this read-only
    # cross-agent audit and prevents 20x repeated GET pagination. Validate
    # EVERY durable intent/receipt from the same observed server epoch.
    inventory = all_issues()
    recorded = comments()
    native = native_links()
    data = []
    for i in range(COUNT):
        expected_body = child_body(i)
        marker_value = marker("child", i)
        hits = [
            row for row in inventory
            if isinstance(row.get("body"), str)
            and row["body"].startswith(marker_value)
            and row.get("pull_request") is None
        ]
        if len(hits) > 1:
            raise RuntimeError("duplicate physical Child for a logical agent")
        if not hits:
            continue
        ch = hits[0]
        if (
            ch.get("body") != expected_body
            or ch.get("title") != child_title(i)
            or ch.get("state") != "open"
            or ch.get("labels")
            or type(ch.get("number")) is not int
            or type(ch.get("id")) is not int
        ):
            raise RuntimeError("Child identity tampered in audit snapshot")
        known = {
            "create-intent": note(
                "create-intent", i,
                issue_body_sha256=hashlib.sha256(
                    expected_body.encode("utf-8")
                ).hexdigest(),
            ),
            "link-intent": note("link-intent", i, internal_issue_id=ch["id"]),
            "allocation": note(
                "allocation", i, child_issue=ch["number"],
                child_internal_id=ch["id"],
            ),
        }
        for stage, expected in known.items():
            rows = [
                c for c in recorded
                if isinstance(c.get("body"), str)
                and c["body"].startswith(marker(stage, i))
            ]
            if (
                len(rows) != 1 or rows[0]["body"] != expected
                or rows[0].get("user", {}).get("login") != AUTHOR
                or rows[0].get("created_at") != rows[0].get("updated_at")
            ):
                raise RuntimeError("Child audit lacks immutable exact stage receipt")
        if ch["id"] not in {x["id"] for x in native}:
            raise RuntimeError("native Child link absent in final audit")
        require_linked(ch)
        data.append((i, ch["number"], ch["id"]))
    permitted = LINKS_EXISTING | {item[2] for item in data}
    if {row["id"] for row in native} != permitted:
        raise RuntimeError("Parent contains unexpected or missing native links")
    if len(data) != len({x[1] for x in data}):
        raise RuntimeError("duplicate physical Child numbers")
    return data

def main():
    require_event()
    parent()
    created = 0
    linked_count = 0
    for agent in range(COUNT):
        # Every run may create at most five new Child Issues and their
        # corresponding links/receipts, limiting GitHub mutation burst.
        if created >= MAX_NEW:
            break
        ch, just_created = ensure_created(agent)
        created += int(just_created)
        linked_count += int(ensure_link(agent, ch))
        ensure_record(agent, ch)
        parent()
    complete = audit_all()
    result = {
        "status": "PASS" if len(complete) == COUNT else "PARTIAL",
        "expected": COUNT, "observed_allocations": len(complete),
        "created_this_run": created, "links_this_run": linked_count,
        "total_native_links": len(native_links()),
        "no_samuel_admission": True,
        "max_child_creates_per_run": MAX_NEW,
        "actual_sigkill_after_remote_post": any(i == 1 for i, _, _ in complete),
        "ack_loss_simulation": "caller_discarded_real_POST_response_for_000",
    }
    print("LIVE_CHILD_BATCH_282=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--sigkill-worker":
            require_event()
            create_worker(int(sys.argv[2]))
        else:
            raise SystemExit(main())
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print("LIVE_CHILD_BATCH_282=BLOCKED_SCOPE "
              + type(exc).__name__ + " " + str(exc)[:160], file=sys.stderr)
        raise SystemExit(2)
