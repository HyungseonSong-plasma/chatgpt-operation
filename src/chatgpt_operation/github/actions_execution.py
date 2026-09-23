"""Deterministic GitHub Actions execution-route selection."""

from __future__ import annotations

from typing import Any

ROUTE_PRECEDENCE = {
    "DIRECT_WORKFLOW_DISPATCH": 0,
    "EXISTING_WORKFLOW_TRIGGER": 1,
    "RERUN_EXISTING_RUN": 2,
    "ONE_SHOT_WORKFLOW": 3,
}

TERMINAL_STATUSES = {
    "ROUTE_READY",
    "NO_AUTHORIZED_ROUTE",
    "NO_SAFE_EQUIVALENT_ROUTE",
}


class ActionsExecutionError(ValueError):
    """Raised when execution-route evidence is malformed."""


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ActionsExecutionError(f"{field} must be boolean")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActionsExecutionError(f"{field} must be a non-empty string")
    return value


def _validate_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActionsExecutionError("request must be an object")
    required = {
        "required_claim",
        "required_event",
        "require_exact_head",
        "mutation_authorized",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ActionsExecutionError("request missing: " + ", ".join(missing))

    required_claim = _require_string(value["required_claim"], "required_claim")
    required_event = value["required_event"]
    if required_event is not None:
        required_event = _require_string(required_event, "required_event")

    return {
        "required_claim": required_claim,
        "required_event": required_event,
        "require_exact_head": _require_bool(
            value["require_exact_head"], "require_exact_head"
        ),
        "mutation_authorized": _require_bool(
            value["mutation_authorized"], "mutation_authorized"
        ),
    }


def _validate_route(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActionsExecutionError(f"routes[{index}] must be an object")

    fields = {
        "id",
        "kind",
        "available",
        "authorized",
        "event",
        "preserves_exact_head",
        "observable",
        "bounded",
        "requires_repository_mutation",
        "cleanup_available",
    }
    missing = sorted(fields - set(value))
    if missing:
        raise ActionsExecutionError(
            f"routes[{index}] missing: " + ", ".join(missing)
        )

    kind = _require_string(value["kind"], f"routes[{index}].kind")
    if kind not in ROUTE_PRECEDENCE:
        raise ActionsExecutionError(
            f"routes[{index}].kind unsupported: {kind}"
        )

    event = _require_string(value["event"], f"routes[{index}].event")
    route = {
        "id": _require_string(value["id"], f"routes[{index}].id"),
        "kind": kind,
        "available": _require_bool(
            value["available"], f"routes[{index}].available"
        ),
        "authorized": _require_bool(
            value["authorized"], f"routes[{index}].authorized"
        ),
        "event": event,
        "preserves_exact_head": _require_bool(
            value["preserves_exact_head"],
            f"routes[{index}].preserves_exact_head",
        ),
        "observable": _require_bool(
            value["observable"], f"routes[{index}].observable"
        ),
        "bounded": _require_bool(
            value["bounded"], f"routes[{index}].bounded"
        ),
        "requires_repository_mutation": _require_bool(
            value["requires_repository_mutation"],
            f"routes[{index}].requires_repository_mutation",
        ),
        "cleanup_available": _require_bool(
            value["cleanup_available"],
            f"routes[{index}].cleanup_available",
        ),
    }

    if kind == "ONE_SHOT_WORKFLOW" and not route["requires_repository_mutation"]:
        raise ActionsExecutionError(
            "ONE_SHOT_WORKFLOW must declare requires_repository_mutation=true"
        )
    return route


def _rejection_reasons(
    request: dict[str, Any], route: dict[str, Any]
) -> list[str]:
    reasons: list[str] = []
    if not route["available"]:
        reasons.append("UNAVAILABLE")
    if not route["authorized"]:
        reasons.append("UNAUTHORIZED")
    required_event = request["required_event"]
    if required_event is not None and route["event"] != required_event:
        reasons.append("WRONG_EVENT")
    if request["require_exact_head"] and not route["preserves_exact_head"]:
        reasons.append("HEAD_NOT_PRESERVED")
    if not route["observable"]:
        reasons.append("NOT_OBSERVABLE")
    if not route["bounded"]:
        reasons.append("UNBOUNDED")
    if (
        route["requires_repository_mutation"]
        and not request["mutation_authorized"]
    ):
        reasons.append("MUTATION_NOT_AUTHORIZED")
    if route["kind"] == "ONE_SHOT_WORKFLOW" and not route["cleanup_available"]:
        reasons.append("CLEANUP_UNAVAILABLE")
    return reasons


def _handoffs(route: dict[str, Any]) -> list[str]:
    handoffs: list[str] = []
    if route["requires_repository_mutation"]:
        handoffs.append("repository-mutation")
    handoffs.append("github-actions-observation")
    if route["kind"] == "ONE_SHOT_WORKFLOW":
        handoffs.append("repository-mutation:cleanup")
    return handoffs


def evaluate(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Select the safest sufficient route using deterministic precedence."""
    if not isinstance(snapshot, dict):
        raise ActionsExecutionError("snapshot must be an object")
    if snapshot.get("schema_version") != 1:
        raise ActionsExecutionError("schema_version must be 1")

    request = _validate_request(snapshot.get("request"))
    raw_routes = snapshot.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ActionsExecutionError("routes must be a non-empty array")

    routes = [_validate_route(value, index) for index, value in enumerate(raw_routes)]
    ids = [route["id"] for route in routes]
    if len(ids) != len(set(ids)):
        raise ActionsExecutionError("route ids must be unique")

    rejected = []
    eligible = []
    for route in routes:
        reasons = _rejection_reasons(request, route)
        if reasons:
            rejected.append({"id": route["id"], "kind": route["kind"], "reasons": reasons})
        else:
            eligible.append(route)

    if eligible:
        selected = min(
            eligible,
            key=lambda route: (ROUTE_PRECEDENCE[route["kind"]], route["id"]),
        )
        cleanup_required = selected["kind"] == "ONE_SHOT_WORKFLOW"
        return {
            "status": "ROUTE_READY",
            "required_claim": request["required_claim"],
            "required_event": request["required_event"],
            "route_id": selected["id"],
            "route_kind": selected["kind"],
            "event": selected["event"],
            "requires_repository_mutation": selected[
                "requires_repository_mutation"
            ],
            "cleanup_required": cleanup_required,
            "handoffs": _handoffs(selected),
            "rejected_routes": rejected,
        }

    available = [route for route in routes if route["available"]]
    authorized = [route for route in available if route["authorized"]]
    if available and not authorized:
        status = "NO_AUTHORIZED_ROUTE"
    else:
        status = "NO_SAFE_EQUIVALENT_ROUTE"

    return {
        "status": status,
        "required_claim": request["required_claim"],
        "required_event": request["required_event"],
        "route_id": None,
        "route_kind": None,
        "event": None,
        "requires_repository_mutation": False,
        "cleanup_required": False,
        "handoffs": [],
        "rejected_routes": rejected,
    }


def self_test() -> int:
    """Small packaged smoke test for CLI/runtime wiring."""
    result = evaluate(
        {
            "schema_version": 1,
            "request": {
                "required_claim": "exact-head validation",
                "required_event": None,
                "require_exact_head": True,
                "mutation_authorized": True,
            },
            "routes": [
                {
                    "id": "dispatch",
                    "kind": "DIRECT_WORKFLOW_DISPATCH",
                    "available": False,
                    "authorized": True,
                    "event": "workflow_dispatch",
                    "preserves_exact_head": True,
                    "observable": True,
                    "bounded": True,
                    "requires_repository_mutation": False,
                    "cleanup_available": True,
                },
                {
                    "id": "one-shot",
                    "kind": "ONE_SHOT_WORKFLOW",
                    "available": True,
                    "authorized": True,
                    "event": "push",
                    "preserves_exact_head": True,
                    "observable": True,
                    "bounded": True,
                    "requires_repository_mutation": True,
                    "cleanup_available": True,
                },
            ],
        }
    )
    if result["status"] != "ROUTE_READY":
        raise ActionsExecutionError("self-test did not find a route")
    if result["route_kind"] != "ONE_SHOT_WORKFLOW":
        raise ActionsExecutionError("self-test did not select one-shot route")
    return 0
