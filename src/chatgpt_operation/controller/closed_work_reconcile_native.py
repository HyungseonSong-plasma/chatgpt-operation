"""One-shot, owner-comment-triggered, native #255/#256 StateKernel reconciliation.

Live activation requires the separately protected workflow on main. The
external scheduler has no access to this writer. No untrusted issue, branch,
repository or work ID arguments are accepted. All GitHub evidence comes from
authenticated native REST, and mutation endpoints are fixed to the two
existing global #44 ledger comments using the StateKernel writer.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from chatgpt_operation.github.actions_runtime import (
    ActionsApiError, GitHubActionsTransport,
)
from .closed_work_reconciliation import (
    APPROVAL_MARKER, BRANCH, REPO, ExternalReconciliationError,
    plan_external_noop_reconciliation,
)
from .durable_state import (
    can_rollover_state, find_state_comment, load_state_comment,
    state_write_request,
)
from .issue_ingestion import (
    ADMISSION_MARKER, decode_admission_ledger, encode_admission_ledger,
)
from .scoped_wake_native import _stable_pages
from .state_persistence import persist_state_write

EXPECTED_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class NoopReleaseError(RuntimeError):
    pass


def _comment(comments: list[dict[str, Any]], marker: str):
    found = [
        value for value in comments
        if marker in str(value.get("body", ""))
    ]
    if len(found) != 1:
        raise NoopReleaseError("authoritative ledger comment missing or ambiguous")
    return found[0]


def _missing(transport: GitHubActionsTransport, path: str) -> bool:
    try:
        transport.get(path)
    except ActionsApiError as exc:
        if exc.status == 404:
            return True
        raise NoopReleaseError("native GitHub absence proof unavailable") from exc
    return False


def _main_head(transport: GitHubActionsTransport) -> str:
    branch = transport.get("/branches/main")
    if not isinstance(branch, dict) or not isinstance(branch.get("commit"), dict):
        raise NoopReleaseError("repository default branch unavailable")
    head = branch["commit"].get("sha")
    if not isinstance(head, str) or not EXPECTED_COMMIT.fullmatch(head):
        raise NoopReleaseError("invalid native main source SHA")
    return head


def reconcile_native(transport: GitHubActionsTransport, *,
                     expected_main_sha: str,
                     owner_event_comment_id: int) -> dict[str, Any]:
    if transport.repository != REPO:
        raise NoopReleaseError("wrong native repository")
    if (
        not isinstance(expected_main_sha, str)
        or not EXPECTED_COMMIT.fullmatch(expected_main_sha)
        or type(owner_event_comment_id) is not int
        or owner_event_comment_id <= 0
    ):
        raise NoopReleaseError("invalid canonical owner event/source SHA")
    if _main_head(transport) != expected_main_sha:
        raise NoopReleaseError("main moved before reconciliation")
    issue255 = transport.get("/issues/255")
    issue256 = transport.get("/issues/256")
    comments255 = _stable_pages(
        transport, "/issues/255/comments", limit=500,
    )
    comments256 = _stable_pages(
        transport, "/issues/256/comments", limit=500,
    )
    approval = [
        c for c in comments255
        if isinstance(c.get("body"), str)
        and c["body"].startswith(APPROVAL_MARKER)
    ]
    if len(approval) != 1 or approval[0].get("id") != owner_event_comment_id:
        raise NoopReleaseError("owner event comment not bound to authenticated readback")
    if not _missing(transport, f"/git/ref/heads/{BRANCH}"):
        raise NoopReleaseError("target Git ref is still present")
    if not _missing(transport, f"/branches/{BRANCH}"):
        raise NoopReleaseError("target branch still present")
    matching = transport.get(f"/git/matching-refs/heads/{BRANCH}")
    if matching != []:
        raise NoopReleaseError("target matching Git refs are not empty")
    opted = _stable_pages(
        transport, "/issues", limit=1000,
        filters={"state": "open", "labels": "samuel"},
    )
    if any(x.get("pull_request") is None for x in opted):
        raise NoopReleaseError("another open samuel task is still present")

    global_comments = _stable_pages(
        transport, "/issues/44/comments", limit=500,
    )
    durable = load_state_comment(global_comments)
    admission_comment = _comment(global_comments, ADMISSION_MARKER)
    if durable is None:
        raise NoopReleaseError("global ResearchState missing")
    ledger = decode_admission_ledger(str(admission_comment["body"]))

    if (
        durable.research_id == "issue:255"
        and durable.retirement is not None
        and can_rollover_state(durable)
        and ledger.get("issue:255", {}).get("status") == "complete"
        and ledger.get("issue:256", {}).get("status") == "complete"
    ):
        return {
            "status": "NO_MUTATION_NEEDED", "research_id": "issue:255",
            "revision": durable.revision, "historical_escalation_preserved": True,
            "ledger_255": "complete", "ledger_256": "complete",
        }

    proposed, updated, proof = plan_external_noop_reconciliation(
        durable, ledger,
        repository=REPO, source_main_sha=expected_main_sha,
        issue255=issue255, issue256=issue256,
        comments255=comments255, comments256=comments256,
        ref_absent=True, branch_absent=True, matching_refs_empty=True,
    )
    # Native exact-source and mutable global readback preflight again before
    # the FIRST write. A single shared Bootstrap concurrency group serializes
    # the two native writers; no API supports atomic multi-comment CAS.
    if _main_head(transport) != expected_main_sha:
        raise NoopReleaseError("main changed before retirement writer")
    before_write = _stable_pages(
        transport, "/issues/44/comments", limit=500,
    )
    original_state = load_state_comment(before_write)
    original_admission = _comment(before_write, ADMISSION_MARKER)
    if (
        original_state != durable
        or original_admission.get("id") != admission_comment.get("id")
        or decode_admission_ledger(str(original_admission["body"])) != ledger
    ):
        raise NoopReleaseError("global owner/Admission ledger changed before write")
    if updated != ledger:
        status, response = transport.request(
            "PATCH", f"/issues/comments/{admission_comment['id']}",
            payload={"body": encode_admission_ledger(updated)},
        )
        if (
            status != 200 or not isinstance(response, dict)
            or response.get("id") != admission_comment["id"]
        ):
            raise NoopReleaseError("terminal Admission status update not confirmed")
        after_admission = _stable_pages(
            transport, "/issues/44/comments", limit=500,
        )
        if decode_admission_ledger(
            str(_comment(after_admission, ADMISSION_MARKER)["body"])
        ) != updated or load_state_comment(after_admission) != durable:
            raise NoopReleaseError("terminal Admission readback mismatch")

    # The existing repository-owned StateKernel persistence boundary enforces
    # observed exact previous revision and byte-equivalent readback. It may
    # PATCH only the one authoritative Issue #44 State comment.
    final_before = _stable_pages(
        transport, "/issues/44/comments", limit=500,
    )
    request = state_write_request(final_before, proposed)
    persisted = persist_state_write(
        transport, issue_number=44, request=request,
    )
    final = _stable_pages(
        transport, "/issues/44/comments", limit=500,
    )
    actual = load_state_comment(final)
    if (
        actual != proposed or actual.predispatch_failures != durable.predispatch_failures
        or not can_rollover_state(actual)
        or decode_admission_ledger(
            str(_comment(final, ADMISSION_MARKER)["body"])
        ) != updated
    ):
        raise NoopReleaseError("postwrite owner or historical error mismatch")
    return {
        "status": "PASS", "research_id": "issue:255",
        "revision": persisted.revision,
        "historical_escalation_preserved": True,
        "ledger_255": "complete", "ledger_256": "complete",
        "owner_comment_id": proof["owner_comment_id"],
        "provider_executed": False,
    }


def main() -> int:
    env = os.environ
    if (
        env.get("GITHUB_REPOSITORY") != REPO
        or env.get("GITHUB_EVENT_NAME") != "issue_comment"
        or env.get("GITHUB_REF") != "refs/heads/main"
        or not env.get("GITHUB_TOKEN")
    ):
        raise NoopReleaseError("not the canonical owner-comment main runner")
    sha = env.get("GITHUB_SHA")
    if not isinstance(sha, str) or not EXPECTED_COMMIT.fullmatch(sha):
        raise NoopReleaseError("runner lacks exact main SHA")
    event_path = env.get("GITHUB_EVENT_PATH", "")
    with open(event_path, encoding="utf-8") as handle:
        event = json.load(handle)
    if (
        event.get("action") != "created"
        or event.get("issue", {}).get("number") != 255
        or event.get("comment", {}).get("user", {}).get("login")
            != "HyungseonSong-plasma"
        or not str(event.get("comment", {}).get("body", "")).startswith(APPROVAL_MARKER)
    ):
        raise NoopReleaseError("untrusted or mismatched native issue_comment event")
    ident = event["comment"].get("id")
    if type(ident) is not int:
        raise NoopReleaseError("missing immutable owner comment ID")
    native = GitHubActionsTransport(REPO, env["GITHUB_TOKEN"])
    result = reconcile_native(
        native, expected_main_sha=sha, owner_event_comment_id=ident,
    )
    print("SAMUEL_CLOSED_WORK_RECONCILIATION=" + result["status"])
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print("SAMUEL_CLOSED_WORK_RECONCILIATION=BLOCKED", file=sys.stderr)
        print(type(exc).__name__ + ": " + str(exc)[:180], file=sys.stderr)
        raise SystemExit(2)
