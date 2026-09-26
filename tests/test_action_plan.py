from chatgpt_operation.controller.action_plan import (
    ActionPlan,
    ActionPlanError,
    ExecutorKind,
)
from chatgpt_operation.repository.action_plan_adapter import (
    repository_operation_id,
    to_repository_manifest,
)


def repository_plan(**overrides):
    raw = {
        "schema_version": 1,
        "research_id": "r-41",
        "stage": "implement",
        "executor": "repository_mutation",
        "expected_observation": "file mutation is verified by readback",
        "payload": {
            "schema_version": 1,
            "repository": "o/r",
            "resource": "file",
            "action": "create",
            "target": {"path": "docs/result.txt", "branch": "issue-41-x"},
            "expected": {"absent": True},
            "desired": {"content": "result\n"},
            "commit_message": "Add result",
        },
    }
    raw.update(overrides)
    return ActionPlan.from_dict(raw)


def test_action_plan_idempotency_is_stable_across_mapping_order():
    first = repository_plan()
    reordered_payload = {
        "commit_message": "Add result",
        "desired": {"content": "result\n"},
        "expected": {"absent": True},
        "target": {"branch": "issue-41-x", "path": "docs/result.txt"},
        "action": "create",
        "resource": "file",
        "repository": "o/r",
        "schema_version": 1,
    }
    second = repository_plan(payload=reordered_payload)
    assert first.idempotency_key == second.idempotency_key


def test_action_plan_rejects_unknown_fields():
    try:
        repository_plan(unbounded_shell_command="rm -rf /")
    except ActionPlanError:
        pass
    else:
        raise AssertionError("unknown action-plan fields must fail closed")


def test_action_plan_rejects_terminal_origin_stage():
    try:
        repository_plan(stage="complete")
    except ActionPlanError:
        pass
    else:
        raise AssertionError("completed research cannot originate execution")


def test_high_risk_action_plan_requires_escalation():
    plan = repository_plan(
        decision_risk={
            "impact": 0.9,
            "uncertainty": 0.8,
            "irreversibility": 0.9,
        }
    )
    assert plan.requires_escalation()


def test_repository_adapter_reuses_existing_mutation_contract():
    plan = repository_plan()
    manifest = to_repository_manifest(plan, expected_repository="o/r")
    assert manifest.repository == "o/r"
    assert manifest.resource == "file"
    assert manifest.action == "create"
    assert len(repository_operation_id(plan)) == 64


def test_repository_adapter_rejects_malformed_mutation_payload():
    plan = repository_plan(
        payload={
            "schema_version": 1,
            "repository": "o/r",
            "resource": "issue",
            "action": "update",
            "target": {},
            "expected": {},
            "desired": {},
        }
    )
    try:
        to_repository_manifest(plan)
    except ActionPlanError:
        pass
    else:
        raise AssertionError("unsupported mutation resource must fail closed")


def test_repository_adapter_rejects_wrong_executor():
    plan = repository_plan(
        executor=ExecutorKind.GITHUB_ACTIONS.value,
        payload={"workflow": "ci.yml", "ref": "issue-41-x"},
    )
    try:
        to_repository_manifest(plan)
    except ActionPlanError:
        pass
    else:
        raise AssertionError("wrong executor must not reach repository mutation")


def test_repository_adapter_rejects_repository_mismatch():
    plan = repository_plan()
    try:
        to_repository_manifest(plan, expected_repository="different/repo")
    except ActionPlanError:
        pass
    else:
        raise AssertionError("cross-repository plan must fail closed")


def test_repository_adapter_blocks_escalated_plan():
    plan = repository_plan(
        decision_risk={
            "impact": 1.0,
            "uncertainty": 1.0,
            "irreversibility": 1.0,
        }
    )
    try:
        to_repository_manifest(plan)
    except ActionPlanError:
        pass
    else:
        raise AssertionError("escalated plan must not execute")
