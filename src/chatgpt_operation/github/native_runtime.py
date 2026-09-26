"""GitHub REST transport implementing Samuel native mutation ports."""
from __future__ import annotations

import json
from urllib import error, request
from typing import Any

from .native_executor import NativeGitHubAction


class NativeGitHubRuntimeError(RuntimeError):
    pass


class GitHubNativeTransport:
    def __init__(self, repository: str, token: str, *, api_url: str = "https://api.github.com", api_version: str = "2022-11-28"):
        if "/" not in repository or not token:
            raise NativeGitHubRuntimeError("repository owner/name and token are required")
        self.repository=repository
        self.token=token
        self.api_url=api_url.rstrip("/")
        self.api_version=api_version

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data=None if payload is None else json.dumps(payload).encode("utf-8")
        req=request.Request(
            self.api_url+path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": self.api_version,
                "Content-Type": "application/json",
                "User-Agent": "samuel-native-github-executor",
            },
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                raw=response.read()
                return {} if not raw else json.loads(raw.decode("utf-8"))
        except error.HTTPError as exc:
            body=exc.read().decode("utf-8", errors="replace")
            raise NativeGitHubRuntimeError(f"GitHub API {method} {path} failed: {exc.code} {body[:500]}") from exc

    def read_state(self, action: NativeGitHubAction, target: dict[str, Any]) -> dict[str, Any]:
        repo=target["repository"]
        if repo != self.repository:
            raise NativeGitHubRuntimeError("runtime repository mismatch")
        if action is NativeGitHubAction.MERGE_PR:
            number=int(target["number"])
            pr=self._call("GET", f"/repos/{repo}/pulls/{number}")
            sha=pr["head"]["sha"]
            status=self._call("GET", f"/repos/{repo}/commits/{sha}/status")
            return {
                "merged": bool(pr.get("merged", False)),
                "head_sha": sha,
                "mergeable": pr.get("mergeable"),
                "ci": status.get("state"),
            }
        if action in {NativeGitHubAction.COMMENT_ISSUE, NativeGitHubAction.CLOSE_ISSUE}:
            number=int(target["number"])
            issue=self._call("GET", f"/repos/{repo}/issues/{number}")
            state={"issue_state": issue["state"]}
            if action is NativeGitHubAction.COMMENT_ISSUE:
                marker=target.get("marker")
                comments=self._call("GET", f"/repos/{repo}/issues/{number}/comments?per_page=100")
                state["comment_present"]=bool(marker) and any(marker in item.get("body","") for item in comments)
            return state
        if action is NativeGitHubAction.DISPATCH_WORKFLOW:
            return {"dispatched": False, "ref": target.get("ref")}
        raise NativeGitHubRuntimeError("unsupported action")

    def mutate(self, action: NativeGitHubAction, target: dict[str, Any]) -> dict[str, Any]:
        repo=target["repository"]
        if repo != self.repository:
            raise NativeGitHubRuntimeError("runtime repository mismatch")
        if action is NativeGitHubAction.MERGE_PR:
            payload={"sha": target["expected_head_sha"]}
            if target.get("merge_method"):
                payload["merge_method"]=target["merge_method"]
            return self._call("PUT", f"/repos/{repo}/pulls/{int(target['number'])}/merge", payload)
        if action is NativeGitHubAction.COMMENT_ISSUE:
            return self._call("POST", f"/repos/{repo}/issues/{int(target['number'])}/comments", {"body": target["body"]})
        if action is NativeGitHubAction.CLOSE_ISSUE:
            return self._call("PATCH", f"/repos/{repo}/issues/{int(target['number'])}", {"state":"closed"})
        if action is NativeGitHubAction.DISPATCH_WORKFLOW:
            self._call("POST", f"/repos/{repo}/actions/workflows/{target['workflow']}/dispatches", {"ref":target["ref"],"inputs":target.get("inputs",{})})
            return {"accepted": True}
        raise NativeGitHubRuntimeError("unsupported action")
