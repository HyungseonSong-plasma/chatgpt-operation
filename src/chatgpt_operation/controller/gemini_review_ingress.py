"""Fail-closed, credential-free ingress for an owner-labeled Gemini review Issue.

This module does not call GitHub or Gemini. A trusted Actions preparation job
fetches live PR metadata, exact diff and complete changed-file inventory.
Only the validated packet is passed to the separate model-execution job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from .gemini_review_adapter import ReviewError, canonical_bytes, validate_packet

HOST_REPOSITORY = "HyungseonSong-plasma/chatgpt-operation"
SOURCE_REPOSITORY = "HyungseonSong-plasma/codeQA"  # v0.1 owner-approved allowlist
TRIGGER_LABEL = "samuel/gemini-review-approved"
MAX_ISSUE_BYTES = 52_000
MAX_DIFF_BYTES = 192_000
MAX_FILES = 50
_REQUEST_TYPE = "SAMUEL_GEMINI_REVIEW"
_TITLE_PREFIX = "[Gemini Review]"
_SAFE_NUMBER = re.compile(r"[1-9][0-9]{0,6}\Z")


def _object(raw: Any, label: str) -> dict:
    if not isinstance(raw, dict):
        raise ReviewError(f"{label} must be object")
    return raw


def _member(raw: Any, *path: str):
    value = raw
    for key in path:
        value = _object(value, ".".join(path)).get(key)
    return value


def issue_identity(event: object, *, source_repository: str = SOURCE_REPOSITORY) -> dict:
    """Reject untrusted event before any potentially chargeable model action."""
    e = _object(event, "event")
    issue = _object(e.get("issue"), "issue")
    if _member(e, "repository", "full_name") != HOST_REPOSITORY:
        raise ReviewError("wrong Samuel host repository")
    if e.get("action") != "labeled" or _member(e, "label", "name") != TRIGGER_LABEL:
        raise ReviewError("event is not explicit Gemini review authorization")
    if _member(e, "sender", "login") != "HyungseonSong-plasma":
        raise ReviewError("only the owner may label a Gemini review")
    if _member(issue, "user", "login") != "HyungseonSong-plasma":
        raise ReviewError("review request must originate from owner")
    if issue.get("pull_request") is not None or issue.get("state") != "open":
        raise ReviewError("review request must be an open issue")
    if not isinstance(issue.get("title"), str) or not issue["title"].startswith(_TITLE_PREFIX):
        raise ReviewError("review request title prefix missing")
    issue_number = issue.get("number")
    if type(issue_number) is not int or issue_number < 1:
        raise ReviewError("issue identity missing")
    labels = issue.get("labels")
    if not isinstance(labels, list) or not any(
        isinstance(x, dict) and x.get("name") == TRIGGER_LABEL for x in labels
    ):
        raise ReviewError("approval label not present on the issue")

    body = issue.get("body")
    if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_ISSUE_BYTES:
        raise ReviewError("issue request body absent or oversized")
    try:
        req = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise ReviewError("review issue body must be JSON") from exc
    if not isinstance(req, dict) or set(req) != {
        "schema_version", "request_type", "pr_number", "packet",
    }:
        raise ReviewError("review issue has invalid request fields")
    if type(req["schema_version"]) is not int or req["schema_version"] != 1:
        raise ReviewError("unsupported review issue version")
    if req["request_type"] != _REQUEST_TYPE:
        raise ReviewError("invalid review issue type")
    pr_number = req["pr_number"]
    if type(pr_number) is not int or not _SAFE_NUMBER.fullmatch(str(pr_number)):
        raise ReviewError("invalid review source PR number")
    packet = validate_packet(req["packet"])
    if packet["repository"] != source_repository:
        raise ReviewError("source repository is not allowlisted")
    if packet["base_sha"] == packet["head_sha"]:
        raise ReviewError("review comparison has identical commits")
    return {
        "host_repository": HOST_REPOSITORY,
        "source_repository": packet["repository"],
        "source_pr_number": pr_number,
        "issue_number": issue_number,
        "packet": packet,
    }


def prepare_verified_review(
    event: object, metadata: object, diff: str, files: object,
    *, source_repository: str = SOURCE_REPOSITORY,
) -> dict:
    """Cross-check caller packet against current trusted GitHub observations."""
    ident = issue_identity(event, source_repository=source_repository)
    packet = ident["packet"]
    pr = _object(metadata, "source PR")
    if pr.get("number") != ident["source_pr_number"] or pr.get("state") != "open":
        raise ReviewError("source pull request is absent or not open")
    if _member(pr, "base", "ref") != "main":
        raise ReviewError("source PR must target main for v0.1 pilot")
    if _member(pr, "base", "sha") != packet["base_sha"]:
        raise ReviewError("base SHA became stale")
    if _member(pr, "head", "sha") != packet["head_sha"]:
        raise ReviewError("head SHA became stale")
    if (_member(pr, "base", "repo", "full_name") != source_repository or
            _member(pr, "head", "repo", "full_name") != source_repository):
        raise ReviewError("source pull request repository identity changed")
    if not isinstance(diff, str) or not diff or len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise ReviewError("trusted PR diff unavailable or oversized")
    if diff != packet["diff"]:
        raise ReviewError("supplied PR diff differs from trusted GitHub diff")
    if hashlib.sha256(diff.encode("utf-8")).hexdigest() != packet["diff_sha256"]:
        raise ReviewError("trusted diff digest mismatch")
    changed_count = pr.get("changed_files")
    if type(changed_count) is not int or not 1 <= changed_count <= MAX_FILES:
        raise ReviewError("source PR changed-file count unsupported")
    if not isinstance(files, list) or len(files) != changed_count:
        raise ReviewError("source PR file inventory incomplete")
    observed = []
    for f in files:
        path = _object(f, "changed file").get("filename")
        if not isinstance(path, str):
            raise ReviewError("invalid trusted file path")
        observed.append(path)
    if len(set(observed)) != len(observed) or set(observed) != set(packet["changed_paths"]):
        raise ReviewError("changed-file inventory does not match exact PR")
    request_id = hashlib.sha256(canonical_bytes(packet)).hexdigest()
    return {
        "schema_version": 1,
        "status": "VERIFIED_REVIEW_REQUEST",
        "host_repository": HOST_REPOSITORY,
        "issue_number": ident["issue_number"],
        "source_pr_number": ident["source_pr_number"],
        "packet": packet,
        "request_sha256": request_id,
        "authority": {
            "gemini_github_access": False,
            "merge_authorized": False,
            "mutation_authorized": False,
            "source_evidence": "EXACT_GITHUB_DIFF_AND_PR_METADATA",
        },
    }


def _read_json(path: str, *, max_bytes: int = 240_000):
    data = Path(path).read_bytes()
    if len(data) > max_bytes:
        raise ReviewError("source evidence exceeds limit")
    return json.loads(data.decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Samuel owner-approved Issue review ingress")
    p.add_argument("--event", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--identify-only", action="store_true")
    p.add_argument("--pr-meta")
    p.add_argument("--pr-diff")
    p.add_argument("--pr-files")
    args = p.parse_args(argv)
    try:
        event = _read_json(args.event, max_bytes=400_000)
        if args.identify_only:
            info = issue_identity(event)
            result = {k: v for k, v in info.items() if k != "packet"}
        else:
            if not all((args.pr_meta, args.pr_diff, args.pr_files)):
                raise ReviewError("trusted PR metadata, diff and files are mandatory")
            pr = _read_json(args.pr_meta)
            diff_bytes = Path(args.pr_diff).read_bytes()
            if len(diff_bytes) > MAX_DIFF_BYTES:
                raise ReviewError("trusted diff too large")
            diff = diff_bytes.decode("utf-8")
            files = _read_json(args.pr_files)
            result = prepare_verified_review(event, pr, diff, files)
        Path(args.output).write_text(
            json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (ReviewError, ValueError, UnicodeError, OSError, TypeError) as exc:
        # Error detail must not contain the Issue body, raw model content or token.
        print("SAMUEL_GEMINI_INGRESS=UNKNOWN (" + type(exc).__name__ + ")", file=sys.stderr)
        return 2
    print("SAMUEL_GEMINI_INGRESS=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
