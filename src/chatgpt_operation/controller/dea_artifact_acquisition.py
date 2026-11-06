"""Read-only GitHub API acquisition for DEA candidate evidence.

This is an operator-invoked tool. It never dispatches workflows or performs
GitHub mutation. Only a protected, trusted execution environment can turn
a run's metadata into an independently authenticated producer attestation.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler, Request, build_opener,
)

from chatgpt_operation.controller.dea_evidence_gate import (
    EvidenceGateError, check_evidence_bundle,
)

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_API_HOST = "api.github.com"
_MAX_JSON_BYTES = 4_000_000
_MAX_ARCHIVE_BYTES = 25_000_000


class AcquisitionError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _trusted_archive_location(value: str) -> bool:
    """Prevent token forwarding and server-side redirect to arbitrary hosts."""
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower()
        return (
            u.scheme == "https" and u.username is None and u.password is None
            and (u.port is None or u.port == 443)
            and (
                host.endswith(".blob.core.windows.net")
                or host.endswith(".actions.githubusercontent.com")
                or host.endswith(".githubusercontent.com")
            )
        )
    except ValueError:
        return False


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AcquisitionError("duplicate keys in GitHub JSON response")
        result[key] = value
    return result


def _json_bytes(data: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeError, ValueError) as exc:
        raise AcquisitionError("malformed GitHub API JSON") from exc
    if not isinstance(obj, dict):
        raise AcquisitionError("GitHub API response must be an object")
    return obj


def _fetch_bytes(url: str, *, token: str | None, max_bytes: int,
                 allow_archive_redirect: bool) -> bytes:
    opener = build_opener(_NoRedirect())
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "DEA-ReadOnly-Evidence/0.2",
    }
    if token:
        if urlsplit(url).hostname != _API_HOST:
            raise AcquisitionError("token only allowed for GitHub API origin")
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers, method="GET")
    try:
        with closing(opener.open(request, timeout=60)) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise AcquisitionError("response exceeds bounded read limit")
            return data
    except HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308) and allow_archive_redirect:
            destination = exc.headers.get("Location", "")
            if not _trusted_archive_location(destination):
                raise AcquisitionError("untrusted artifact redirect target") from exc
            # IMPORTANT: the presigned archive URL receives NO GitHub token.
            # NoRedirect is used again to prevent any additional redirect
            # to a private network, different origin, or untrusted host.
            return _fetch_bytes(destination, token=None, max_bytes=max_bytes,
                                allow_archive_redirect=False)
        raise AcquisitionError("GitHub evidence request unsuccessful: HTTP "
                               + str(exc.code)) from exc
    except (OSError, URLError) as exc:
        raise AcquisitionError("GitHub evidence read unavailable") from exc


def fetch_artifact_bundle(*, repository: str, run_id: int, artifact_id: int,
                          token: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Read metadata directly from GitHub and download a bounded artifact.

    This acquisition does NOT fetch or assert the producing job attestation.
    """
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise AcquisitionError("invalid repository name")
    if any(type(x) is not int or x <= 0 for x in (run_id, artifact_id)):
        raise AcquisitionError("invalid numeric run/artifact identity")
    if not isinstance(token, str) or not token.strip():
        raise AcquisitionError("read-only GitHub API token is required")
    base = "https://api.github.com/repos/" + repository
    run = _json_bytes(_fetch_bytes(
        base + "/actions/runs/" + str(run_id),
        token=token, max_bytes=_MAX_JSON_BYTES, allow_archive_redirect=False,
    ))
    listing = _json_bytes(_fetch_bytes(
        base + "/actions/runs/" + str(run_id) + "/artifacts?per_page=100",
        token=token, max_bytes=_MAX_JSON_BYTES, allow_archive_redirect=False,
    ))
    archive = _fetch_bytes(
        base + "/actions/artifacts/" + str(artifact_id) + "/zip",
        token=token, max_bytes=_MAX_ARCHIVE_BYTES,
        allow_archive_redirect=True,
    )
    return run, listing, archive


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("repository", "workflow-path", "candidate-head",
                "analyzed-source-sha", "oracle-revision-sha",
                "measurement-set-sha", "artifact-name"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--source-repo-root", type=Path, required=True)
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--artifact-id", type=int, required=True)
    args = p.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        if not token:
            raise AcquisitionError("GH_TOKEN or GITHUB_TOKEN required")
        run, listing, archive = fetch_artifact_bundle(
            repository=args.repository, run_id=args.run_id,
            artifact_id=args.artifact_id, token=token,
        )
        receipt = check_evidence_bundle(
            source_repo_root=args.source_repo_root,
            github_run=run, github_artifact_listing=listing,
            downloaded_archive_zip=archive,
            expected_repository=args.repository,
            expected_workflow_path=args.workflow_path,
            candidate_head_sha=args.candidate_head,
            analyzed_source_sha=args.analyzed_source_sha,
            oracle_revision_sha=args.oracle_revision_sha,
            measurement_set_sha=args.measurement_set_sha,
            run_id=args.run_id, artifact_id=args.artifact_id,
            artifact_name=args.artifact_name,
        )
    except (AcquisitionError, EvidenceGateError) as exc:
        # No secret, presigned URL or candidate-controlled JSON is printed.
        print(json.dumps({
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "reason": str(exc) if isinstance(exc, EvidenceGateError)
            else "evidence acquisition or trust validation failed",
            "pareto_eligible": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    # Success means readback inspection completed, not fitness admission.
    return 0


if __name__ == "__main__":
    sys.exit(main())
