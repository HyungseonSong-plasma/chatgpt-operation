"""Bounded, read-only GitHub history collection, not denial-source attestation.

The injected authenticated REST reader must return decoded JSON for the exact
repository and endpoint. GitHub metadata does not expose external screening
logs or prove that deleted records never existed.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Callable, Protocol

from .legacy_work_identity import HistoryEvidence, RecoveryRequest


class HistoryReadError(RuntimeError):
    pass


class GetJSON(Protocol):
    def __call__(self, path: str, query: dict[str, int]) -> object: ...


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise HistoryReadError(reason)


def _obj(value: object) -> dict:
    _require(isinstance(value, dict), "expected JSON object")
    return value


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _count(value: object) -> int:
    _require(type(value) is int and value >= 0, "invalid advertised count")
    return value


def _sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True)
class GitHubHistorySnapshot:
    request: RecoveryRequest
    issue_number: int
    pr_numbers: tuple[int, ...]
    canonical_json: str

    @property
    def source_ref(self) -> str:
        return "github-visible-history:sha256:" + sha256(self.canonical_json.encode()).hexdigest()

    @property
    def external_history_complete(self) -> bool:
        return False

    def records(self) -> dict:
        # Return a detached copy, never mutable backing evidence.
        return json.loads(self.canonical_json)


class GitHubHistoryReader:
    """Collect visible issue/PR comments, reviews, review comments and commits.

    PR list and target PR are supplied by trusted work-scope configuration.
    This list is NOT proof of all historical PRs for the work. Reject a moving
    target, count mismatch, duplicate records, truncated pagination, forks or
    divergent repeated observations. Double reads are not an atomic snapshot.
    """
    def __init__(self, get_json: GetJSON, *, issue_number: int,
                 target_pr: int, historical_prs: tuple[int, ...] = (), max_pages: int = 10):
        if not callable(get_json) or not _positive(issue_number) or not _positive(target_pr):
            raise ValueError("authenticated reader and target numbers required")
        if not isinstance(historical_prs, tuple) or any(not _positive(n) for n in historical_prs):
            raise ValueError("invalid historical PR inventory")
        numbers = (target_pr,) + historical_prs
        if issue_number in numbers or len(set(numbers)) != len(numbers) or len(numbers) > 32:
            raise ValueError("ambiguous or oversized PR inventory")
        if type(max_pages) is not int or not 1 <= max_pages <= 20:
            raise ValueError("invalid pagination bound")
        self._get = get_json
        self._issue = issue_number
        self._target = target_pr
        self._prs = numbers
        self._max_pages = max_pages

    def _pages(self, path: str, key: str, expected: int | None = None) -> list[dict]:
        rows, seen = [], set()
        for page in range(1, self._max_pages + 1):
            batch = self._get(path, {"per_page": 100, "page": page})
            _require(isinstance(batch, list) and len(batch) <= 100, "invalid page")
            for row in batch:
                obj = _obj(row)
                identity = obj.get(key)
                _require(_sha(identity) if key == "sha" else _positive(identity), "invalid record identity")
                _require(identity not in seen, "duplicate paginated record")
                seen.add(identity)
                rows.append(obj)
            if len(batch) < 100:
                _require(expected is None or len(rows) == expected, "advertised record count mismatch")
                return rows
        raise HistoryReadError("pagination exhausted without terminal page")

    def _read(self, request: RecoveryRequest) -> dict:
        root = "/repos/" + request.scope.repository
        repo = _obj(self._get(root, {}))
        _require(repo.get("id") == request.scope.repository_id and type(repo.get("id")) is int
                 and repo.get("full_name") == request.scope.repository, "repository binding mismatch")
        issue_path = f"{root}/issues/{self._issue}"
        issue = _obj(self._get(issue_path, {}))
        _require(issue.get("id") == request.scope.issue_id and type(issue.get("id")) is int
                 and issue.get("number") == self._issue and "pull_request" not in issue,
                 "issue binding mismatch")
        result = {"repository": {"id": repo["id"], "full_name": repo["full_name"]},
                  "issue": issue, "issue_comments": self._pages(issue_path + "/comments", "id", _count(issue.get("comments"))),
                  "pull_requests": []}
        for number in self._prs:
            path = f"{root}/pulls/{number}"
            pr = _obj(self._get(path, {}))
            _require(pr.get("number") == number and _positive(pr.get("id")), "PR binding mismatch")
            head, base = _obj(pr.get("head")), _obj(pr.get("base"))
            for ref in (head, base):
                _require(_obj(ref.get("repo")).get("id") == request.scope.repository_id and _sha(ref.get("sha")),
                         "PR repository or SHA mismatch")
            if number == self._target:
                _require(head["sha"] == request.target_head, "target HEAD changed")
            count = _count(pr.get("commits"))
            _require(0 < count <= 250, "PR commit inventory outside API bound")
            commits = self._pages(path + "/commits", "sha", count)
            _require(commits[-1]["sha"] == head["sha"], "PR commit tip mismatch")
            result["pull_requests"].append({"pr": pr, "commits": commits,
                "comments": self._pages(f"{root}/issues/{number}/comments", "id", _count(pr.get("comments"))),
                "review_comments": self._pages(path + "/comments", "id", _count(pr.get("review_comments"))),
                "reviews": self._pages(path + "/reviews", "id")})
        # Bind evidence digest to the request, including stable work anchor.
        result["request"] = {"work_anchor": request.scope.work_anchor, "target_head": request.target_head,
                             "issue_number": self._issue, "target_pr": self._target, "pr_numbers": self._prs}
        return result

    def collect(self, request: RecoveryRequest) -> GitHubHistorySnapshot:
        if not isinstance(request, RecoveryRequest):
            raise HistoryReadError("typed request required")
        try:
            first = _canonical(self._read(request))
            second = _canonical(self._read(request))
            _require(first == second, "visible history changed during collection")
        except HistoryReadError:
            raise
        except Exception as exc:
            raise HistoryReadError("history collection failed") from exc
        return GitHubHistorySnapshot(request, self._issue, self._prs, first)

    def read_evidence(self, request: RecoveryRequest, *,
                      resolve: Callable[[GitHubHistorySnapshot], HistoryEvidence]) -> HistoryEvidence:
        """S1 reader bridge. Resolver is separately trusted, not a text parser.

        S1 still needs independent scope and coverage verifiers; this method
        does not set coverage_ref or no_original_id_issued from GitHub data.
        """
        snapshot = self.collect(request)
        evidence = resolve(snapshot)
        _require(isinstance(evidence, HistoryEvidence) and evidence.request == request
                 and evidence.source_ref == snapshot.source_ref, "resolver evidence binding mismatch")
        return evidence
