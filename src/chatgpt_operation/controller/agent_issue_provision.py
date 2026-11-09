"""Crash-recoverable Child Issue provisioning plans; parent Bootstrap owns writes.

Plan ONE next REST operation at a time from fresh GitHub reads. All requests
are read-only until a separately authenticated Bootstrap writer executes the
returned method/path/body. Never auto-create admitted ('samuel'-labelled) work.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Protocol

from .agent_issue_partition import (
    ASSIGNMENT_MARKER, AgentIssueError, _decode, _json, _name,
    _positive, _sha, child_issue_body, make_assignment, validate_assignment,
)
from .progress_resume import create_checkpoint

PROVISION_MARKER = "<!-- samuel-child-provision-v1:"
PARENT_ASSIGNMENT_MARKER = "<!-- samuel-parent-child-allocation-v1:"
_FIELDS = frozenset({
    "schema_version", "provision_id", "repository", "parent_issue",
    "agent_id", "work_id", "plan_sha256", "policy_sha256",
    "source_head_sha", "units",
})
_MAX_ISSUES = 1000
_MAX_SUBISSUES = 100
_MAX_PARENT_COMMENTS = 500


class ProvisionError(AgentIssueError):
    pass


class IssueReader(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


def _digest(value: Mapping[str, Any], key: str) -> str:
    return hashlib.sha256(_json({k: v for k, v in value.items() if k != key})).hexdigest()


def create_provision(
    *, repository: str, parent_issue: int, agent_id: str, work_id: str,
    plan_sha256: str, policy_sha256: str, source_head_sha: str,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    spec = {
        "schema_version": 1, "repository": repository,
        "parent_issue": parent_issue, "agent_id": agent_id,
        "work_id": work_id, "plan_sha256": plan_sha256,
        "policy_sha256": policy_sha256,
        "source_head_sha": source_head_sha, "units": units,
    }
    spec["provision_id"] = _digest(spec, "provision_id")
    return validate_provision(spec)


def validate_provision(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict) or set(spec) != _FIELDS or spec["schema_version"] != 1:
        raise ProvisionError("invalid Child provisioning schema")
    _name(spec["agent_id"], "agent_id")
    _name(spec["work_id"], "work_id")
    _positive(spec["parent_issue"], "parent_issue")
    if not isinstance(spec["repository"], str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", spec["repository"]
    ):
        raise ProvisionError("invalid provisioning repository")
    for key in ("plan_sha256", "policy_sha256"):
        _sha(spec[key], key)
    if not isinstance(spec["source_head_sha"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", spec["source_head_sha"]
    ):
        raise ProvisionError("unreviewed source commit identity")
    create_checkpoint(
        work_id=spec["work_id"], plan_sha256=spec["plan_sha256"],
        policy_sha256=spec["policy_sha256"], units=spec["units"],
    )
    if _sha(spec["provision_id"], "provision_id") != _digest(spec, "provision_id"):
        raise ProvisionError("provision identity mismatch")
    return json.loads(_json(spec))


def _encode(marker: str, digest: str, obj: Mapping[str, Any]) -> str:
    return marker + digest + " -->\n```json\n" + _json(obj).decode("utf-8") + "\n```"


def _decode_marker(body: Any, marker: str, identity_field: str) -> dict[str, Any]:
    if not isinstance(body, str):
        raise ProvisionError("provision comment must be text")
    match = re.fullmatch(
        re.escape(marker) + r"([0-9a-f]{64}) -->\n```json\n(.*?)\n```",
        body, re.DOTALL,
    )
    if match is None:
        raise ProvisionError("invalid provisioning marker")
    try:
        obj = json.loads(match.group(2))
    except json.JSONDecodeError as exc:
        raise ProvisionError("invalid provisioning JSON") from exc
    if (
        not isinstance(obj, dict) or obj.get(identity_field) != match.group(1)
        or _json(obj).decode("utf-8") != match.group(2)
    ):
        raise ProvisionError("invalid provisioning marker identity")
    return obj


def initial_child_body(spec: dict[str, Any]) -> str:
    v = validate_provision(spec)
    return _encode(PROVISION_MARKER, v["provision_id"], v)


def parent_allocation_body(assignment: dict[str, Any]) -> str:
    v = validate_assignment(assignment)
    return _encode(PARENT_ASSIGNMENT_MARKER, v["assignment_id"], v)


def _assignment_spec(assignment: dict[str, Any]) -> dict[str, Any]:
    v = validate_assignment(assignment)
    return create_provision(**{
        k: v[k] for k in _FIELDS if k not in ("provision_id", "schema_version")
    })


def _snapshot(reader: IssueReader, path: str, *, limit: int) -> list[dict[str, Any]]:
    """Read all GitHub REST pages twice, fail closed on unstable inventory."""
    def fetch() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        ids: set[int] = set()
        for page in range(1, limit // 100 + 2):
            rows = reader.get(path, query={"per_page": "100", "page": str(page)})
            if not isinstance(rows, list) or len(rows) > 100:
                raise ProvisionError("GitHub inventory page is invalid")
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or type(row.get("id")) is not int or row["id"] < 1
                    or type(row.get("number", 1)) is not int
                ):
                    raise ProvisionError("malformed GitHub inventory item")
                if row["id"] in ids:
                    raise ProvisionError("duplicate GitHub object in inventory")
                ids.add(row["id"])
                result.append(row)
            if len(result) > limit:
                raise ProvisionError("GitHub inventory is over safety limit")
            if len(rows) < 100:
                return result
        raise ProvisionError("GitHub inventory did not terminate")
    first, second = fetch(), fetch()
    if _json(first) != _json(second):
        raise ProvisionError("GitHub inventory changed during readback")
    return second


def _matches_issue(item: dict[str, Any], spec: dict[str, Any]) -> bool:
    body = item.get("body")
    if not isinstance(body, str):
        return False
    if PROVISION_MARKER in body:
        candidate = validate_provision(
            _decode_marker(body, PROVISION_MARKER, "provision_id")
        )
        return candidate == spec
    if ASSIGNMENT_MARKER in body:
        candidate = validate_assignment(_decode(body, ASSIGNMENT_MARKER))
        return _assignment_spec(candidate) == spec
    return False


def _registered_allocations(
    comments: list[dict[str, Any]], *,
    trusted_author: str,
) -> list[dict[str, Any]]:
    result = []
    for item in comments:
        body = item.get("body")
        if not isinstance(body, str) or PARENT_ASSIGNMENT_MARKER not in body:
            continue
        if (
            item.get("user", {}).get("login") != trusted_author
            or item.get("created_at") != item.get("updated_at")
        ):
            raise ProvisionError("parent allocation was not immutable or trusted")
        raw = _decode_marker(body, PARENT_ASSIGNMENT_MARKER, "assignment_id")
        result.append(validate_assignment(raw))
    if len(result) > 50:
        raise ProvisionError("parent allocation capacity exceeded")
    by_agent = {}
    by_issue = {}
    for assignment in result:
        agent = assignment["agent_id"]
        number = assignment["child_issue"]
        if agent in by_agent and by_agent[agent] != assignment:
            raise ProvisionError("conflicting parent assignment for agent")
        if number in by_issue and by_issue[number] != assignment:
            raise ProvisionError("two agents assigned the same Child")
        by_agent[agent] = assignment
        by_issue[number] = assignment
    return result


def _plan(status: str, *, method: str | None = None,
          path: str | None = None, payload: dict[str, Any] | None = None,
          assignment: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status, "method": method, "path": path,
        "payload": payload, "assignment": assignment,
        "parent_state_patch": False, "merge_authorized": False,
    }


def plan_next_child_provision(
    reader: IssueReader, spec: dict[str, Any], *,
    parent_issue: Mapping[str, Any],
    trusted_author: str = "github-actions[bot]",
) -> dict[str, Any]:
    """Return a single safe operation; writer must re-plan after EVERY write.

    The trusted Bootstrap alone may execute this plan. No caller can use
    GitHub Issue labels or child-supplied data as an authorization source.
    """
    s = validate_provision(spec)
    if (
        not isinstance(parent_issue, Mapping)
        or parent_issue.get("number") != s["parent_issue"]
        or parent_issue.get("state") != "open"
        or parent_issue.get("url") != "https://api.github.com/repos/"
            + s["repository"] + "/issues/" + str(s["parent_issue"])
    ):
        raise ProvisionError("parent live Issue identity mismatch")
    if not trusted_author:
        raise ProvisionError("trusted writer comment author is required")
    # This is a bounded review-only scanner: never use a worker-supplied Issue
    # number or guess a missing result from partial GitHub pagination.
    all_issues = _snapshot(reader, "/issues?state=all", limit=_MAX_ISSUES)
    matching = [
        item for item in all_issues
        if item.get("pull_request") is None and _matches_issue(item, s)
    ]
    if len(matching) > 1:
        raise ProvisionError("duplicate provisional/final Child Issues found")
    if matching:
        child = matching[0]
        if (
            child.get("state") != "open"
            or type(child.get("number")) is not int
            or child["number"] == s["parent_issue"]
        ):
            raise ProvisionError("Child Issue identity or state mismatch")
        if child.get("labels"):
            labels = child["labels"]
            if any(x == "samuel" or isinstance(x, dict)
                   and x.get("name") == "samuel" for x in labels):
                raise ProvisionError("Child mistakenly admitted to parent queue")
        assignment = make_assignment(
            repository=s["repository"], parent_issue=s["parent_issue"],
            child_issue=child["number"], agent_id=s["agent_id"],
            work_id=s["work_id"], plan_sha256=s["plan_sha256"],
            policy_sha256=s["policy_sha256"],
            source_head_sha=s["source_head_sha"], units=s["units"],
        )
    else:
        # The actor must be the verified exclusive parent Bootstrap. This
        # function itself makes no network writes.
        return _plan(
            "CREATE_CHILD", method="POST", path="/issues",
            payload={
                "title": "[Samuel Child] " + s["agent_id"] + " — " + s["work_id"],
                "body": initial_child_body(s), "labels": [],
            },
        )
    if child["body"] != child_issue_body(assignment):
        if child["body"] != initial_child_body(s):
            raise ProvisionError("Child Issue was edited or hijacked")
        return _plan(
            "FINALIZE_CHILD", method="PATCH",
            path="/issues/" + str(child["number"]),
            payload={"body": child_issue_body(assignment)},
            assignment=assignment,
        )

    # Native GitHub Sub-issue linkage is mandatory; simple text references
    # do not count. GitHub REST POST expects the internal issue.id, not number.
    linked = _snapshot(
        reader, "/issues/" + str(s["parent_issue"]) + "/sub_issues",
        limit=_MAX_SUBISSUES,
    )
    matching_links = [x for x in linked if x.get("number") == child["number"]]
    if matching_links and (
        len(matching_links) != 1 or matching_links[0].get("id") != child["id"]
    ):
        raise ProvisionError("ambiguous native Sub-issue relation")
    if not matching_links:
        return _plan(
            "LINK_CHILD", method="POST",
            path="/issues/" + str(s["parent_issue"]) + "/sub_issues",
            payload={"sub_issue_id": child["id"]},
            assignment=assignment,
        )

    comments = _snapshot(
        reader, "/issues/" + str(s["parent_issue"]) + "/comments",
        limit=_MAX_PARENT_COMMENTS,
    )
    approved = _registered_allocations(comments, trusted_author=trusted_author)
    for old in approved:
        if old["agent_id"] == s["agent_id"] and old != assignment:
            raise ProvisionError("parent agent allocation conflict")
        if old["child_issue"] == child["number"] and old != assignment:
            raise ProvisionError("parent Child ownership conflict")
    exact = [x for x in approved if x == assignment]
    if not exact:
        return _plan(
            "RECORD_PARENT_ASSIGNMENT", method="POST",
            path="/issues/" + str(s["parent_issue"]) + "/comments",
            payload={"body": parent_allocation_body(assignment)},
            assignment=assignment,
        )
    return _plan("READY", assignment=assignment)
