from chatgpt_operation.controller.action_plan import ActionPlan, ActionPlanError
from chatgpt_operation.github.action_plan_adapter import plan_github_actions


def actions_plan(**overrides):
    raw = {
        "schema_version": 1,
        "research_id": "r-41",
        "stage": "execute",
        "executor": "github_actions",
        "expected_observation": "selected route is observable and bounded",
        "payload": {
            "schema_version": 1,
            "request": {
                "required_claim": "exact-head validation",
                "required_event": None,
                "require_exact_head": True,
                "mutation_authorized": False,
            },
            "routes": [
                {
                    "id": "dispatch",
                    "kind": "DIRECT_WORKFLOW_DISPATCH",
                    "available": True,
                    "authorized": True,
                    "event": "workflow_dispatch",
                    "preserves_exact_head": True,
                    "observable": True,
                    "bounded": True,
                    "requires_repository_mutation": False,
                    "cleanup_available": True,
                }
            ],
        },
    }
    raw.update(overrides)
    return ActionPlan.from_dict(raw)


def test_github_actions_adapter_reuses_existing_route_planner():
    result = plan_github_actions(actions_plan())
    assert result["status"] == "ROUTE_READY"
    assert result["route_kind"] == "DIRECT_WORKFLOW_DISPATCH"
    assert result["route_id"] == "dispatch"


def test_github_actions_adapter_fails_closed_on_invalid_payload():
    plan = actions_plan(payload={"schema_version": 1})
    try:
        plan_github_actions(plan)
    except ActionPlanError:
        pass
    else:
        raise AssertionError("invalid Actions payload must fail closed")


def test_github_actions_adapter_rejects_wrong_executor():
    plan = actions_plan(
        executor="repository_mutation",
        payload={
            "schema_version": 1,
            "repository": "o/r",
            "resource": "branch",
            "action": "create",
            "target": {"name": "issue-41-x"},
            "expected": {"absent": True},
            "desired": {"sha": "a" * 40},
        },
    )
    try:
        plan_github_actions(plan)
    except ActionPlanError:
        pass
    else:
        raise AssertionError("wrong executor must not reach Actions planner")


def test_github_actions_adapter_blocks_escalated_plan():
    plan = actions_plan(
        decision_risk={
            "impact": 0.9,
            "uncertainty": 0.9,
            "irreversibility": 0.9,
        }
    )
    try:
        plan_github_actions(plan)
    except ActionPlanError:
        pass
    else:
        raise AssertionError("escalated plan must not execute")
