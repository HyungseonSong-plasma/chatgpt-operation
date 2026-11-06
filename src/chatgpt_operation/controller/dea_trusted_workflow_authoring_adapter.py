"""Opt-in, fail-closed GitHub write boundary for DEA #254 Workflow Draft PR.

This is an EFFECTFUL adapter, unlike the read-only planning preflight.
It must be deployed by a separately trusted operator with a scoped GitHub
App credential and a real CommonPreWriteGate. It is NOT wired into the
ChatGPT-hosted github-connector, and is NOT an authorization grant by itself.

One workflow file, one reviewable branch, and one Draft PR. No merge,
review submission, workflow dispatch, policy mutation, or unrestricted API.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from hashlib import sha1, sha256
import json
import re
from typing import Any, Protocol

from chatgpt_operation.controller.dea_workflow_authoring_preflight import (
    BRANCH, PATH, REPO, WORK_ID, WorkflowDraftIntent,
    assess_workflow_draft_intent,
)
from chatgpt_operation.repository.blocker_gate import CommonPreWriteGate
from chatgpt_operation.repository.blocker_triage import logical_intent_id
from chatgpt_operation.controller.dea_operator_delegation import OperatorDelegationGate


class WorkflowAuthoringError(RuntimeError):
    pass


class GitHubBoundTransport(Protocol):
    repository: str

    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any:
        ...

    def request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> Any:
        ...


POLICY_PATH = "automation/samuel/repository-mutation-policy.json"
REFERENCE_PATH = "docs/dea-v02-protected-producer-smoke.proposed.yml"
PINNED_REVIEWED_BLUEPRINT_BLOB_SHA = "8215bb3d07f3918c6a3ecd9f92e152538625691a"
PR_TITLE = "feat(dea): adopt protected signed Artifact smoke Workflow (#254)"
PR_BODY = (
    "Draft for human review only. Related #254 and approval comment "
    "https://github.com/HyungseonSong-plasma/chatgpt-operation/"
    "issues/254#issuecomment-6685977537 . "
    "The proposed Workflow must not be merged, dispatched, signed, "
    "or treated as DEA Fitness evidence without separate human authority. "
    "All source bytes originate from reviewed main."
)
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_SOURCE_BYTES = 64000


@dataclass(frozen=True)
class WorkflowDraftReceipt:
    status: str
    pr_number: int
    pr_url: str
    source_base_sha: str
    head_sha: str
    workflow_sha256: str
    draft: bool = True
    merged: bool = False
    executable_authority: bool = False


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise WorkflowAuthoringError(reason)


def _github_content_bytes(value: Any, *, max_size: int) -> bytes:
    _require(
        isinstance(value, dict) and value.get("encoding") == "base64"
        and isinstance(value.get("content"), str)
        and isinstance(value.get("sha"), str),
        "GITHUB_CONTENT_NOT_ATTESTED",
    )
    try:
        raw = base64.b64decode(value["content"].replace("\n", ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise WorkflowAuthoringError("GITHUB_CONTENT_BASE64_INVALID") from exc
    _require(0 < len(raw) <= max_size, "GITHUB_CONTENT_OUT_OF_BOUNDS")
    # Verify the blob identity, not just the API's claimed name.
    git_blob = sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw)
    _require(git_blob.hexdigest() == value["sha"], "GITHUB_CONTENT_BLOB_SHA_MISMATCH")
    return raw


def _json_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_POLICY_KEY")
        result[key] = value
    return result


class TrustedWorkflowDraftAdapter:
    """All GitHub write calls live behind the same exact identity gate.

    A caller-supplied permission Boolean is intentionally unsupported.
    A trusted *deployment*, not this source file, provides the GitHub
    App credential, verified journal reader and independent checkpoint.
    """

    def __init__(
        self, *,
        transport: GitHubBoundTransport,
        blocker_gate: CommonPreWriteGate,
        operator_gate: OperatorDelegationGate,
    ) -> None:
        _require(getattr(transport, "repository", None) == REPO, "FOREIGN_GITHUB_TRANSPORT")
        _require(isinstance(blocker_gate, CommonPreWriteGate), "TRUSTED_GATE_REQUIRED")
        _require(
            callable(getattr(blocker_gate, "trusted_checkpoint_reader", None)),
            "INDEPENDENT_JOURNAL_CHECKPOINT_REQUIRED",
        )
        _require(isinstance(operator_gate, OperatorDelegationGate),
                 "TRUSTED_OPERATOR_DELEGATION_GATE_REQUIRED")
        self.transport = transport
        self.blocker_gate = blocker_gate
        self.operator_gate = operator_gate

    def _read_main(self) -> str:
        response = self.transport.get("/git/ref/heads/main")
        sha = (response.get("object", {}).get("sha")
               if isinstance(response, dict) else None)
        _require(isinstance(sha, str) and SHA40.fullmatch(sha),
                 "CURRENT_MAIN_NOT_VERIFIED")
        return sha

    def _fetch_main_bytes(self, path: str, base_sha: str, limit: int) -> bytes:
        response = self.transport.get("/contents/" + path, query={"ref": base_sha})
        _require(
            isinstance(response, dict) and response.get("path") == path,
            "TRUSTED_PATH_READBACK_FAILED",
        )
        return _github_content_bytes(response, max_size=limit)

    def _require_clear(self, main_sha: str) -> None:
        intent = logical_intent_id(
            repository=REPO, branch=BRANCH,
            work_id=WORK_ID, paths=(PATH,),
        )
        decision = self.blocker_gate.require_clear(
            logical_intent_id=intent, expected_head_sha=main_sha
        )
        _require(decision.no_active_blocker, "ACTIVE_BLOCKER")
        _require(self._read_main() == main_sha, "MAIN_MOVED_AFTER_GATE")

    def _read_branch(self) -> str | None:
        from chatgpt_operation.repository.mutation import ApiError
        try:
            response = self.transport.get("/git/ref/heads/" + BRANCH)
        except ApiError as exc:
            if exc.status == 404:
                return None
            raise
        _require(isinstance(response, dict), "INVALID_BRANCH_READBACK")
        head = response.get("object", {}).get("sha")
        _require(isinstance(head, str) and SHA40.fullmatch(head),
                 "INVALID_BRANCH_SHA")
        return head

    def _read_target(self) -> dict[str, Any] | None:
        from chatgpt_operation.repository.mutation import ApiError
        try:
            return self.transport.get(
                "/contents/" + PATH, query={"ref": BRANCH}
            )
        except ApiError as exc:
            if exc.status == 404:
                return None
            raise

    def _open_prs(self) -> list[dict[str, Any]]:
        response = self.transport.get("/pulls", query={
            "state": "open", "head": "HyungseonSong-plasma:" + BRANCH,
            "base": "main", "per_page": "100",
        })
        _require(isinstance(response, list) and len(response) < 100,
                 "PR_ENUMERATION_UNAVAILABLE_OR_TRUNCATED")
        _require(all(isinstance(x, dict) for x in response),
                 "PR_LIST_INVALID")
        return response

    def prepare_and_create_draft(self, *, expected_main_sha: str) -> WorkflowDraftReceipt:
        """Create the scoped Draft PR; do not run absent an authorized deployment.

        Each write is preceded by source checks / journal gate / SHA lease;
        failed write/readback is a hard stop. Partial GitHub states are
        preserved for human reconciliation, never auto-overwritten.
        """
        _require(
            isinstance(expected_main_sha, str) and SHA40.fullmatch(expected_main_sha),
            "EXPECTED_MAIN_SHA_INVALID",
        )
        observed_main = self._read_main()
        _require(observed_main == expected_main_sha, "MAIN_HEAD_CHANGED")

        # Read true policy and vetted source from EXACT observed main, not
        # a caller-provided JSON, Issue body, PR comment or unreviewed branch.
        policy_raw = self._fetch_main_bytes(POLICY_PATH, observed_main, 100000)
        yaml = self._fetch_main_bytes(REFERENCE_PATH, observed_main, MAX_SOURCE_BYTES)
        _require(
            sha1(b"blob " + str(len(yaml)).encode("ascii") + b"\x00" + yaml).hexdigest()
            == PINNED_REVIEWED_BLUEPRINT_BLOB_SHA,
            "REVIEWED_WORKFLOW_BLUEPRINT_CHANGED",
        )
        try:
            policy = json.loads(policy_raw.decode("utf-8"),
                                object_pairs_hook=_json_unique)
        except (UnicodeError, ValueError) as exc:
            raise WorkflowAuthoringError("MAIN_POLICY_INVALID") from exc
        request = WorkflowDraftIntent(
            repository=REPO, work_id=WORK_ID, path=PATH, action="create",
            branch=BRANCH, base_branch="main",
            expected_base_sha=observed_main, draft=True, content=yaml,
        )
        preflight = assess_workflow_draft_intent(
            request, observed_main_sha=observed_main,
            trusted_reference_yaml=yaml, policy_document=policy,
        )
        _require(not preflight.reasons, "POLICY_OR_SCOPE_DENIED:" + ",".join(preflight.reasons))
        _require(preflight.write_authorized is False, "INVALID_PREFLIGHT_CONTRACT")

        # A required, installed *real* CommonPreWriteGate verifies work
        # registration, complete blocker journal and independently trusted
        # policy-clearance evidence. No false/synthetic approval is accepted.
        self._require_clear(observed_main)

        old_branch_sha = self._read_branch()
        _require(old_branch_sha is None or old_branch_sha == observed_main,
                 "BRANCH_EXISTS_AT_UNRELATED_SHA")
        old_file = self._read_target() if old_branch_sha is not None else None
        _require(old_file is None, "TARGET_FILE_ALREADY_EXISTS")
        _require(not self._open_prs(), "PR_ALREADY_OPEN_FOR_BRANCH")
        self._require_clear(observed_main)

        # Reserve the operator's independently authenticated one-use grant
        # only after policy, journal, branch and PR preflight pass. ChatGPT
        # cannot issue, renew, revoke or attest its own delegation.
        self.operator_gate.require_and_reserve(expected_main_sha=observed_main)
        self._require_clear(observed_main)

        if old_branch_sha is None:
            self.transport.request("POST", "/git/refs", payload={
                "ref": "refs/heads/" + BRANCH,
                "sha": observed_main,
            })
            _require(self._read_branch() == observed_main,
                     "CREATED_BRANCH_SHA_MISMATCH")

        self._require_clear(observed_main)
        _require(self._read_target() is None, "TARGET_RACE_BEFORE_FILE_CREATE")
        write_receipt = self.transport.request("PUT", "/contents/" + PATH, payload={
            "message": "feat(dea): stage human-reviewed protected smoke Workflow (#254)",
            "branch": BRANCH,
            "content": base64.b64encode(yaml).decode("ascii"),
        })
        created_commit_sha = (
            write_receipt.get("commit", {}).get("sha")
            if isinstance(write_receipt, dict) else None
        )
        _require(isinstance(created_commit_sha, str)
                 and SHA40.fullmatch(created_commit_sha),
                 "CREATED_COMMIT_RECEIPT_MISSING")

        # A matching file alone does not prove that the PR branch contains
        # only that file. Bind the GitHub Contents write receipt to an exact
        # single-parent, single-file commit and the current branch head.
        commit = self.transport.get("/commits/" + created_commit_sha)
        _require(
            isinstance(commit, dict)
            and commit.get("sha") == created_commit_sha
            and isinstance(commit.get("parents"), list)
            and len(commit["parents"]) == 1
            and isinstance(commit["parents"][0], dict)
            and commit["parents"][0].get("sha") == observed_main
            and isinstance(commit.get("files"), list)
            and len(commit["files"]) == 1
            and isinstance(commit["files"][0], dict)
            and commit["files"][0].get("filename") == PATH
            and commit["files"][0].get("status") == "added",
            "CREATED_COMMIT_SCOPE_MISMATCH",
        )
        observed_file = self._read_target()
        _require(_github_content_bytes(observed_file, max_size=MAX_SOURCE_BYTES) == yaml,
                 "CREATED_WORKFLOW_BYTES_MISMATCH")
        branch_head = self._read_branch()
        _require(branch_head == created_commit_sha, "BRANCH_MOVED_AFTER_FILE_CREATE")

        self._require_clear(observed_main)
        _require(not self._open_prs(), "CONCURRENT_PR_CREATION")
        _require(self._read_branch() == created_commit_sha,
                 "BRANCH_MOVED_BEFORE_PR_CREATE")
        created = self.transport.request("POST", "/pulls", payload={
            "title": PR_TITLE,
            "body": PR_BODY,
            "head": BRANCH,
            "base": "main",
            "draft": True,
            "maintainer_can_modify": False,
        })
        number = created.get("number") if isinstance(created, dict) else None
        _require(type(number) is int and number > 0, "CREATED_PR_NUMBER_MISSING")
        pr = self.transport.get("/pulls/" + str(number))
        _require(isinstance(pr, dict) and pr.get("number") == number,
                 "CREATED_PR_READBACK_MISSING")
        _require(pr.get("draft") is True and pr.get("state") == "open"
                 and pr.get("merged") is False
                 and pr.get("head", {}).get("ref") == BRANCH
                 and pr["head"].get("sha") == created_commit_sha
                 and pr.get("base", {}).get("ref") == "main"
                 and pr["base"].get("sha") == observed_main,
                 "CREATED_PR_SCOPE_OR_SHA_MISMATCH")
        _require(self._read_branch() == created_commit_sha,
                 "BRANCH_MOVED_AFTER_PR_CREATE")
        _require(self._read_main() == observed_main,
                 "MAIN_MOVED_BEFORE_FINAL_PR_ATTESTATION")
        url = pr.get("html_url")
        _require(isinstance(url, str) and url == (
            "https://github.com/" + REPO + "/pull/" + str(number)
        ), "CREATED_PR_URL_MISMATCH")
        return WorkflowDraftReceipt(
            "DRAFT_PR_CREATED_REVIEW_REQUIRED", number, url, observed_main,
            branch_head, sha256(yaml).hexdigest(),
        )
