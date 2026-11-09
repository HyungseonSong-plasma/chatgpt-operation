"""Safe GitHub artifact ZIP downloader, with NO token forwarding to CDN.

GitHub REST responds 302 with a short-lived signed URL. Resolve the first
redirect using a GitHub API bearer token, then fetch the signed ZIP in a
second unauthenticated request with redirection disabled. The returned bytes
are independently verified against GitHub artifact metadata by the caller.
"""
from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler, Request, build_opener,
)

from .agent_issue_attestation import AgentEvidenceError

_API_VERSION="2026-03-10"
_MAX_ZIP_BYTES=800_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _allowed_download_host(host: str | None) -> bool:
    return bool(
        isinstance(host,str)
        and (
            host=="objects.githubusercontent.com"
            or host.endswith(".actions.githubusercontent.com")
            or host.endswith(".blob.core.windows.net")
        )
    )


def authenticated_artifact_zip(
    *, repository: str, artifact_id: int, token: str,
) -> bytes:
    if (
        not isinstance(repository,str) or repository.count("/")!=1
        or type(artifact_id) is not int or artifact_id<=0
        or not isinstance(token,str) or not token
    ):
        raise AgentEvidenceError("invalid trusted artifact download identity")
    api_url=f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    first=Request(
        api_url,headers={
            "Authorization":"Bearer "+token,
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":_API_VERSION,
            "User-Agent":"samuel-child-evidence-parent-reader",
        },
        method="GET",
    )
    opener=build_opener(_NoRedirect())
    try:
        with opener.open(first,timeout=30):
            raise AgentEvidenceError("GitHub artifact did not return signed redirect")
    except HTTPError as exc:
        if exc.code!=302:
            raise AgentEvidenceError(
                "GitHub artifact redirect request was denied: "+str(exc.code)
            ) from exc
        destination=exc.headers.get("Location")
    except (URLError,OSError,TimeoutError) as exc:
        raise AgentEvidenceError("GitHub artifact API transport failure") from exc

    parsed=urlparse(destination or "")
    if parsed.scheme!="https" or not _allowed_download_host(parsed.hostname):
        raise AgentEvidenceError("GitHub artifact redirect target is not trusted CDN")
    # Critical: DO NOT forward Authorization, token, or API headers here.
    request=Request(destination,headers={
        "User-Agent":"samuel-child-evidence-parent-reader",
    },method="GET")
    try:
        with opener.open(request,timeout=30) as response:
            if response.getcode()!=200:
                raise AgentEvidenceError("signed artifact download did not succeed")
            blob=response.read(_MAX_ZIP_BYTES+1)
    except (HTTPError,URLError,OSError,TimeoutError) as exc:
        raise AgentEvidenceError("signed artifact download failed") from exc
    if not 0<len(blob)<=_MAX_ZIP_BYTES:
        raise AgentEvidenceError("artifact ZIP size exceeded safe bound")
    return blob
