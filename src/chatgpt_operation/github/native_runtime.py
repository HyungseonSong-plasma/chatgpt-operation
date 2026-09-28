"""GitHub REST transport implementing Samuel native mutation ports."""
from __future__ import annotations

import json
from urllib import error, request
from urllib.parse import quote, urlencode
from typing import Any
import time

from .native_executor import NativeGitHubAction


class NativeGitHubRuntimeError(RuntimeError):
    pass


class GitHubNativeTransport:
    def __init__(
        self,
        repository: str,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        api_version: str = "2022-11-28",
    ):
        if "/" not in repository or not token:
            raise NativeGitHubRuntimeError(
                "repository owner/name and token are required"
            )
        self.repository=repository
        self.token=token
        self.api_url=api_url.rstrip("/")
        self.api_version=api_version

    def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
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
            raise NativeGitHubRuntimeError(
                f"GitHub API {method} {path} failed: {exc.code} {body[:500]}"
            ) from exc

    def read_state(
        self,
        action: NativeGitHubAction,
        target: dict[str, Any],
    ) -> dict[str, Any]:
        repo=target["repository"]
        if repo != self.repository:
            raise NativeGitHubRuntimeError("runtime repository mismatch")

        if action is NativeGitHubAction.MERGE_PR:
            number=int(target["number"])
            pr=self._call("GET", f"/repos/{repo}/pulls/{number}")
            sha=pr["head"]["sha"]
            status=self._call("GET", f"/repos/{repo}/commits/{sha}/status")
            trusted_states=[
                str(item.get("state",""))
                for item in status.get("statuses",[])
                if item.get("context")=="samuel/trusted-validation"
            ]
            if trusted_states:
                trusted=trusted_states[0]
                ci=(
                    "success" if trusted=="success"
                    else "failure" if trusted in {"failure","error"}
                    else "pending"
                )
            else:
                checks=self._call(
                    "GET",
                    f"/repos/{repo}/commits/{sha}/check-runs"
                    "?filter=latest&per_page=100",
                )
                runs=checks.get("check_runs",[])
                if not isinstance(runs,list):
                    raise NativeGitHubRuntimeError(
                        "check-runs lookup returned invalid payload"
                    )
                if runs:
                    if any(item.get("status")!="completed" for item in runs):
                        ci="pending"
                    else:
                        conclusions={str(item.get("conclusion") or "") for item in runs}
                        allowed={"success","neutral","skipped"}
                        ci="success" if conclusions and conclusions <= allowed else "failure"
                elif int(status.get("total_count") or 0)>0:
                    combined=str(status.get("state") or "pending")
                    ci=(
                        "success" if combined=="success"
                        else "failure" if combined in {"failure","error"}
                        else "pending"
                    )
                else:
                    ci="pending"
            return {
                "merged": bool(pr.get("merged", False)),
                "head_sha": sha,
                "mergeable": pr.get("mergeable"),
                "ci": ci,
            }

        if action is NativeGitHubAction.CREATE_PR:
            owner=repo.split("/",1)[0]
            query=urlencode({
                "state":"open",
                "head":owner+":"+target["head"],
                "base":target["base"],
                "per_page":"100",
            })
            pulls=self._call("GET", f"/repos/{repo}/pulls?{query}")
            if not isinstance(pulls,list):
                raise NativeGitHubRuntimeError(
                    "create_pr lookup returned invalid payload"
                )
            if len(pulls)>1:
                raise NativeGitHubRuntimeError("create_pr lookup is ambiguous")
            if not pulls:
                return {"pr_present":False}
            pr=pulls[0]
            return {
                "pr_present":True,
                "pr_number":int(pr["number"]),
                "head_sha":pr["head"]["sha"],
                "base":pr["base"]["ref"],
            }

        if action in {
            NativeGitHubAction.COMMENT_ISSUE,
            NativeGitHubAction.CLOSE_ISSUE,
        }:
            number=int(target["number"])
            issue=self._call("GET", f"/repos/{repo}/issues/{number}")
            state={"issue_state": issue["state"]}
            if action is NativeGitHubAction.COMMENT_ISSUE:
                marker=target.get("marker")
                comments=self._call(
                    "GET",
                    f"/repos/{repo}/issues/{number}/comments?per_page=100",
                )
                state["comment_present"]=bool(marker) and any(
                    marker in item.get("body","") for item in comments
                )
            return state

        if action is NativeGitHubAction.DISPATCH_WORKFLOW:
            ref=str(target["ref"])
            expected_head_sha=str(target["expected_head_sha"])
            branch=self._call(
                "GET",
                f"/repos/{repo}/branches/{quote(ref, safe='')}",
            )
            head_sha=str(((branch.get("commit") or {}).get("sha")) or "")
            workflow=str(target["workflow"])
            meta=self._call(
                "GET",
                f"/repos/{repo}/actions/workflows/{quote(workflow, safe='')}",
            )
            workflow_id=meta.get("id")
            if not isinstance(workflow_id,int):
                raise NativeGitHubRuntimeError(
                    "workflow lookup returned invalid id"
                )
            query=urlencode({
                "event":"workflow_dispatch",
                "branch":ref,
                "per_page":"100",
            })
            runs=self._call(
                "GET",
                f"/repos/{repo}/actions/workflows/{workflow_id}/runs?{query}",
            )
            raw_runs=runs.get("workflow_runs",[]) if isinstance(runs,dict) else []
            if not isinstance(raw_runs,list):
                raise NativeGitHubRuntimeError(
                    "workflow runs lookup returned invalid payload"
                )
            started=any(
                isinstance(item,dict)
                and item.get("head_sha")==expected_head_sha
                for item in raw_runs
            )
            return {
                "head_sha":head_sha,
                "ci_started":started,
            }

        raise NativeGitHubRuntimeError("unsupported action")

    def mutate(
        self,
        action: NativeGitHubAction,
        target: dict[str, Any],
    ) -> dict[str, Any]:
        repo=target["repository"]
        if repo != self.repository:
            raise NativeGitHubRuntimeError("runtime repository mismatch")

        if action is NativeGitHubAction.MERGE_PR:
            payload={"sha": target["expected_head_sha"]}
            if target.get("merge_method"):
                payload["merge_method"]=target["merge_method"]
            return self._call(
                "PUT",
                f"/repos/{repo}/pulls/{int(target['number'])}/merge",
                payload,
            )

        if action is NativeGitHubAction.CREATE_PR:
            return self._call(
                "POST",
                f"/repos/{repo}/pulls",
                {
                    "head":target["head"],
                    "base":target["base"],
                    "title":target["title"],
                    "body":target["body"],
                },
            )

        if action is NativeGitHubAction.COMMENT_ISSUE:
            return self._call(
                "POST",
                f"/repos/{repo}/issues/{int(target['number'])}/comments",
                {"body": target["body"]},
            )

        if action is NativeGitHubAction.CLOSE_ISSUE:
            return self._call(
                "PATCH",
                f"/repos/{repo}/issues/{int(target['number'])}",
                {"state":"closed"},
            )

        if action is NativeGitHubAction.DISPATCH_WORKFLOW:
            workflow=quote(str(target["workflow"]),safe="")
            self._call(
                "POST",
                f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
                {"ref":target["ref"]},
            )
            last_state=None
            for attempt in range(20):
                last_state=self.read_state(action,target)
                if last_state.get("ci_started") is True:
                    return {
                        "accepted":True,
                        "verified_visible":True,
                        "attempts":attempt+1,
                    }
                if attempt < 19:
                    time.sleep(0.5)
            return {
                "accepted":True,
                "verified_visible":False,
                "after":last_state,
            }

        raise NativeGitHubRuntimeError("unsupported action")
