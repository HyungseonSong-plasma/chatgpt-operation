"""Durable, repository-qualified Samuel foreign-Issue orchestration.

No Issue body or stored comment grants execution. This source-owned state
machine is deliberately separate from the native issue:N ledger. A reviewed
target code-mutation policy (disabled by default) is required for dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from .action_plan import ActionPlan, ExecutorKind
from .cross_repository_issue_admission import CrossRepositoryIssueSnapshot
from .decisions import DecisionRegistry, GuardOutcome
from .issue_reasoning import IssueReasoningProposal, compile_guarded_action, issue_reasoning_node
from .issue_planning import plan_admitted_issue

WORK_ID = "github:HyungseonSong-plasma/codeQA:issue:92"
TARGET = "HyungseonSong-plasma/codeQA"
SOURCE = "HyungseonSong-plasma/chatgpt-operation"
MARKER = "<!-- samuel-codeqa-foreign-work-ledger-v1 -->"
EXECUTOR_WORKFLOW = "samuel-codeqa-issue-execute.yml"
ALLOWED_PREFIXES = ("src/codeqa/", "tests/", "fixtures/python-sdk/", "docs/")
ALLOWED_ACTIONS = frozenset({"branch.create", "file.create", "file.update", "pr.create", "ci.inspect"})
TERMINAL_CI = frozenset({"success", "failure", "cancelled", "timed_out", "action_required"})
PHASES = frozenset({
    "reasoning_required", "review_required", "dispatch_ready", "dispatched",
    "ci_pending", "revision_required", "ci_verified", "blocked",
})


class ForeignWorkError(ValueError):
    pass


def digest(data: Any) -> str:
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class ForeignWorkState:
    work_id: str
    issue_sha: str
    base_sha: str
    criteria_sha: str
    revision: int
    phase: str
    admission_run_id: int
    action_plan: dict[str, Any] | None = None
    action_id: str | None = None
    receipt: dict[str, Any] | None = None
    target_pr: dict[str, Any] | None = None
    ci_evidence: tuple[dict[str, Any], ...] = ()
    last_failure: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "work_id": self.work_id, "issue_sha": self.issue_sha,
            "base_sha": self.base_sha, "criteria_sha": self.criteria_sha,
            "revision": self.revision, "phase": self.phase,
            "admission_run_id": self.admission_run_id,
            "action_plan": self.action_plan, "action_id": self.action_id,
            "receipt": self.receipt, "target_pr": self.target_pr,
            "ci_evidence": list(self.ci_evidence),
            "last_failure": self.last_failure,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ForeignWorkState":
        required = set(cls(
            WORK_ID, "a"*64, "b"*40, "c"*64, 0, "reasoning_required", 1
        ).to_dict())
        if not isinstance(raw, dict) or set(raw) != required or raw.get("schema_version") != 1:
            raise ForeignWorkError("malformed foreign issue ledger")
        if (raw.get("work_id") != WORK_ID
            or raw.get("phase") not in PHASES
            or type(raw.get("revision")) is not int or raw["revision"] < 0
            or type(raw.get("admission_run_id")) is not int or raw["admission_run_id"] <= 0
            or any(
                not isinstance(raw.get(k), str) or len(raw[k]) != n
                or any(c not in "0123456789abcdef" for c in raw[k])
                for k,n in (("issue_sha",64), ("base_sha",40), ("criteria_sha",64))
            )
            or (raw.get("action_plan") is not None and not isinstance(raw["action_plan"],dict))
            or (raw.get("receipt") is not None and not isinstance(raw["receipt"],dict))
            or (raw.get("target_pr") is not None and not isinstance(raw["target_pr"],dict))
            or not isinstance(raw.get("ci_evidence"),list)
            or (raw.get("last_failure") is not None and not isinstance(raw["last_failure"],str))):
            raise ForeignWorkError("invalid foreign issue ledger fields")
        if raw["action_plan"] is not None:
            plan = ActionPlan.from_dict(raw["action_plan"])
            if plan.research_id != WORK_ID or plan.idempotency_key != raw.get("action_id"):
                raise ForeignWorkError("stored action identity mismatch")
        elif raw.get("action_id") is not None:
            raise ForeignWorkError("orphan foreign action id")
        if raw.get("receipt") is not None and raw.get("action_plan") is None:
            raise ForeignWorkError("orphan execution receipt")
        if raw["phase"] in {"review_required","dispatch_ready","dispatched","ci_pending","ci_verified"} and raw["action_plan"] is None:
            raise ForeignWorkError("active foreign phase lacks typed ActionPlan")
        if raw["phase"] in {"dispatched","ci_pending","ci_verified"} and raw["receipt"] is None:
            raise ForeignWorkError("observed foreign phase lacks dispatch receipt")
        if raw["phase"]=="ci_verified" and (
            not isinstance(raw["target_pr"],dict)
            or not raw["ci_evidence"]
            or any(not isinstance(item,dict)
                   or item.get("conclusion")!="success" or item.get("status")!="completed"
                   for item in raw["ci_evidence"])
        ):
            raise ForeignWorkError("completed CI phase lacks independent success evidence")
        return cls(
            raw["work_id"],raw["issue_sha"],raw["base_sha"],raw["criteria_sha"],
            raw["revision"],raw["phase"],raw["admission_run_id"],
            raw["action_plan"],raw["action_id"],raw["receipt"],raw["target_pr"],
            tuple(raw["ci_evidence"]),raw["last_failure"],
        )


def encode_ledger(state: ForeignWorkState) -> str:
    return MARKER + "\n~~~json\n" + json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":")) + "\n~~~"


def decode_ledger(body: str) -> ForeignWorkState:
    if not isinstance(body,str) or not body.startswith(MARKER + "\n~~~json\n") or not body.endswith("\n~~~"):
        raise ForeignWorkError("foreign state marker or fence invalid")
    raw = json.loads(body.split("~~~json\n",1)[1].rsplit("\n~~~",1)[0])
    return ForeignWorkState.from_dict(raw)


def select_authoritative_ledger(comments: list[dict[str, Any]]) -> tuple[int | None, ForeignWorkState | None]:
    matches = [c for c in comments if isinstance(c,dict) and MARKER in str(c.get("body",""))]
    if len(matches) > 1:
        raise ForeignWorkError("ambiguous authoritative foreign ledgers")
    if not matches:
        return None,None
    item=matches[0]
    actor=item.get("user")
    if (type(item.get("id")) is not int
        or not isinstance(actor,dict)
        or actor.get("login")!="github-actions[bot]"
        or actor.get("id")!=41898282):
        raise ForeignWorkError("foreign ledger must be authored by source GitHub Actions bot")
    return item["id"],decode_ledger(item.get("body",""))


def from_verified_admission(snapshot: CrossRepositoryIssueSnapshot) -> ForeignWorkState:
    if (not isinstance(snapshot, CrossRepositoryIssueSnapshot)
        or snapshot.work_id != WORK_ID
        or snapshot.target_repository != TARGET
        or snapshot.target_repository_id != 1424293498
        or snapshot.target_issue_number != 92
        or snapshot.status != "REASONING_REQUIRED_NO_EXECUTABLE_PLAN"
        or snapshot.action_plan is not None
        or snapshot.merge_authorized is not False
        or len(snapshot.acceptance_criteria) < 1):
        raise ForeignWorkError("unverified cross-repository admission")
    return ForeignWorkState(
        WORK_ID,snapshot.issue_body_sha256,snapshot.target_base_sha,
        digest(list(snapshot.acceptance_criteria)),0,"reasoning_required",
        snapshot.verified_source_run_id,
    )


def reconcile_admission(
    previous: ForeignWorkState | None,
    snapshot: CrossRepositoryIssueSnapshot,
) -> ForeignWorkState:
    observed=from_verified_admission(snapshot)
    if previous is None:
        return observed
    if previous.work_id != observed.work_id:
        raise ForeignWorkError("cross-repository issue substitution")
    if (
        previous.issue_sha != observed.issue_sha
        or previous.base_sha != observed.base_sha
        or previous.criteria_sha != observed.criteria_sha
    ):
        # Stale state is not silently re-authorized after an Issue edit or
        # codeQA main move; a human must review the changed scope.
        if previous.phase == "revision_required" and previous.last_failure=="ADMISSION_FACTS_CHANGED":
            return previous
        return replace(previous,revision=previous.revision+1,
                       phase="revision_required",last_failure="ADMISSION_FACTS_CHANGED")
    return previous


def advance_reviewed_base(
    existing: ForeignWorkState,
    snapshot: CrossRepositoryIssueSnapshot,
) -> ForeignWorkState:
    """Explicitly acknowledge only an unchanged Issue and empty prior work."""
    current=from_verified_admission(snapshot)
    if (
        existing.work_id!=current.work_id
        or existing.issue_sha!=current.issue_sha
        or existing.criteria_sha!=current.criteria_sha
        or existing.base_sha==current.base_sha
        or existing.phase!="revision_required"
        or existing.last_failure!="ADMISSION_FACTS_CHANGED"
        or existing.action_plan is not None or existing.action_id is not None
        or existing.receipt is not None or existing.target_pr is not None
        or bool(existing.ci_evidence)
    ):
        raise ForeignWorkError("reviewed base transition preconditions not met")
    return replace(
        current,
        revision=existing.revision+1,
        admission_run_id=snapshot.verified_source_run_id,
    )


def _plan_to_dict(plan: ActionPlan) -> dict[str, Any]:
    return {
        "schema_version":1,"research_id":plan.research_id,
        "stage":plan.stage.value,"executor":plan.executor.value,
        "payload":plan.payload,"expected_observation":plan.expected_observation,
    }


def validate_foreign_plan(plan: ActionPlan, policy: Mapping[str, Any]) -> None:
    """Require independent codeQA code-scope policy, never the docs proof permit."""
    if (policy.get("schema_version")!=1
        or policy.get("policy_id")!="samuel-codeqa-issue92-execution-v1"
        or policy.get("repository")!=TARGET
        or policy.get("repository_id")!=1424293498
        or policy.get("merge_enabled") is not False
        or policy.get("enabled") is not True
        or policy.get("executor_workflow")!=EXECUTOR_WORKFLOW
        or plan.research_id!=WORK_ID
        or plan.executor is not ExecutorKind.REPOSITORY_MUTATION):
        raise ForeignWorkError("foreign write policy not separately approved")
    p=plan.payload
    if p.get("schema_version") != 1 or p.get("repository")!=TARGET:
        raise ForeignWorkError("foreign plan repository mismatch")
    action=p.get("action")
    resource=p.get("resource")
    if (resource,action) not in {("file","create"),("file","update")}:
        raise ForeignWorkError("only file create/update allowed after review")
    target=p.get("target")
    if not isinstance(target,dict):
        raise ForeignWorkError("foreign file target missing")
    path=target.get("path")
    branch=target.get("branch")
    if (not isinstance(path,str) or not path
        or path.startswith("/") or "\\" in path
        or any(segment in ("", ".", "..") for segment in path.split("/"))
        or not isinstance(branch,str)
        or branch!=policy.get("head_branch")
        or branch in ("main","master")
        or not isinstance(policy.get("path_prefixes"),list)
        or not any(path.startswith(prefix) for prefix in policy["path_prefixes"])
        or any(path.startswith(prefix) for prefix in (".github/", "automation/", "skills/"))):
        raise ForeignWorkError("target file/branch outside approved codeQA policy")
    if set(p) - {"schema_version","repository","resource","action","target","expected","desired","commit_message"}:
        raise ForeignWorkError("foreign plan contains unexpected fields")
    expected=p.get("expected")
    desired=p.get("desired")
    if not isinstance(expected,dict) or not isinstance(desired,dict):
        raise ForeignWorkError("expected and desired conditions required")
    if not isinstance(desired.get("content"),str) or not desired["content"]:
        raise ForeignWorkError("nonempty desired file content required")
    from chatgpt_operation.repository.action_plan_adapter import to_repository_manifest
    to_repository_manifest(plan,expected_repository=TARGET)


def plan_next_cycle(
    state: ForeignWorkState,
    context: Mapping[str, Any],
    *,
    registry: DecisionRegistry,
    reasoning_runner: Callable[[str,dict[str,Any],int,str|None],dict[str,Any]] | None,
    execution_policy: Mapping[str,Any],
) -> ForeignWorkState:
    """Produce a typed guarded proposal, but require separate review for writes."""
    if state.phase!="reasoning_required" or reasoning_runner is None:
        return state
    scope=context.get("cross_repository_scope")
    if (not isinstance(scope,dict) or scope.get("work_id") != WORK_ID
        or scope.get("verified") is not True
        or scope.get("issue_body_sha256") != state.issue_sha
        or scope.get("target_base_sha") != state.base_sha
        or digest(context.get("acceptance_criteria"))!=state.criteria_sha
        or context.get("completion_allowed") is not False):
        raise ForeignWorkError("reasoning scope no longer verified")
    work={"work_id":WORK_ID,"repository":TARGET,"issue_number":92,
          "title":"codeQA #92 independently verified acceptance work","body":""}
    envelope=plan_admitted_issue(
        work,registry=registry,cross_repository_verified=True
    ).envelope
    request_context=dict(context)
    request_context["source_issue_body_untrusted"]=True
    request_context["execution_policy_enabled"]=execution_policy.get("enabled") is True
    from .reasoning import ReasoningRequest
    proposal=issue_reasoning_node(max_attempts=2).run(
        ReasoningRequest("issue_reasoning",request_context),reasoning_runner
    )
    outcome,plan,_=compile_guarded_action(proposal,envelope)
    if plan is None:
        return replace(state,revision=state.revision+1,phase="reasoning_required"
                       if outcome is GuardOutcome.CONTINUE else "revision_required",
                       last_failure=None if outcome is GuardOutcome.CONTINUE else "NO_APPROVED_ACTION_PLAN")
    if plan.research_id!=WORK_ID:
        raise ForeignWorkError("provider returned wrong repository-qualified action")
    # A disabled policy means the proposal may be *stored for review* but
    # never deemed dispatch-ready. Validate structural safety against a
    # candidate with enabled=True without authorizing execution.
    inspect=dict(execution_policy)
    inspect["enabled"]=True
    validate_foreign_plan(plan,inspect)
    return replace(state,revision=state.revision+1,
                   phase="review_required",action_plan=_plan_to_dict(plan),
                   action_id=plan.idempotency_key,last_failure=None)


def review_for_dispatch(
    state: ForeignWorkState,
    *, execution_policy: Mapping[str,Any],
    approved_action_id: str,
    expected_revision: int,
) -> ForeignWorkState:
    if (state.phase!="review_required"
        or state.revision!=expected_revision
        or state.action_id!=approved_action_id
        or state.action_plan is None):
        raise ForeignWorkError("stale, absent, or unapproved foreign action")
    validate_foreign_plan(ActionPlan.from_dict(state.action_plan),execution_policy)
    return replace(state,revision=state.revision+1,phase="dispatch_ready")


def record_dispatch(
    state: ForeignWorkState,
    receipt: Mapping[str,Any],
    *,
    expected_revision: int,
) -> ForeignWorkState:
    if state.phase!="dispatch_ready" or state.revision!=expected_revision:
        raise ForeignWorkError("stale foreign dispatch attempt")
    if (not isinstance(receipt,dict)
        or type(receipt.get("workflow_run_id")) is not int
        or receipt["workflow_run_id"]<1
        or receipt.get("ref")!="main"):
        raise ForeignWorkError("missing real correlated target workflow receipt")
    return replace(state,revision=state.revision+1,
                   phase="dispatched",receipt=dict(receipt))


def observe_pr_ci(
    state: ForeignWorkState,
    *,
    pr: Mapping[str,Any],
    runs: list[dict[str,Any]],
    required_workflows: tuple[str,...],
) -> ForeignWorkState:
    """Exact PR/commit/workflow correlation; fail means explicit revision."""
    if state.phase not in {"dispatched","ci_pending"} or state.receipt is None:
        raise ForeignWorkError("CI observation lacks prior dispatch")
    if (not isinstance(pr,dict) or pr.get("draft") is not True
        or pr.get("merged") is not False
        or pr.get("state")!="open"
        or pr.get("base",{}).get("ref")!="main"
        or pr.get("head",{}).get("repo",{}).get("full_name")!=TARGET):
        raise ForeignWorkError("untrusted or merged codeQA PR")
    sha=pr.get("head",{}).get("sha")
    branch=pr.get("head",{}).get("ref")
    number=pr.get("number")
    if (not isinstance(sha,str) or len(sha)!=40
        or type(number) is not int or number<1
        or not isinstance(branch,str) or branch=="main"):
        raise ForeignWorkError("PR head identity invalid")
    if (not isinstance(runs,list) or not required_workflows
        or len(set(required_workflows))!=len(required_workflows)):
        raise ForeignWorkError("required CI inventory invalid")
    evidence=[]
    pending=False
    failed=False
    for workflow in required_workflows:
        match=[run for run in runs
               if isinstance(run,dict) and run.get("path")==".github/workflows/"+workflow
               and run.get("head_sha")==sha and run.get("head_branch")==branch
               and run.get("event")=="pull_request"]
        if len(match)!=1:
            pending=True
            continue
        item=match[0]
        if type(item.get("id")) is not int or item["id"]<1:
            raise ForeignWorkError("CI run missing trustworthy run identity")
        status=item.get("status")
        conclusion=item.get("conclusion")
        evidence.append({"workflow":workflow,"run_id":item["id"],
                         "head_sha":sha,"status":status,"conclusion":conclusion})
        if status=="completed":
            if conclusion!="success":
                failed=True
        elif status in {"queued","in_progress","waiting","pending","requested"}:
            pending=True
        else:
            raise ForeignWorkError("CI run status unknown")
    next_phase="revision_required" if failed else "ci_pending" if pending else "ci_verified"
    return replace(state,revision=state.revision+1,phase=next_phase,
                   target_pr={"number":number,"head_sha":sha,"draft":True,
                              "branch":branch},
                   ci_evidence=tuple(evidence),
                   last_failure="EXACT_HEAD_CI_FAILURE" if failed else None)
