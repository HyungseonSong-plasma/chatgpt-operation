import unittest

from chatgpt_operation.github.actions_execution import (
    ActionsExecutionError,
    evaluate,
)


def route(
    route_id,
    kind,
    *,
    available=True,
    authorized=True,
    event="push",
    preserves_exact_head=True,
    observable=True,
    bounded=True,
    requires_repository_mutation=False,
    cleanup_available=True,
):
    return {
        "id": route_id,
        "kind": kind,
        "available": available,
        "authorized": authorized,
        "event": event,
        "preserves_exact_head": preserves_exact_head,
        "observable": observable,
        "bounded": bounded,
        "requires_repository_mutation": requires_repository_mutation,
        "cleanup_available": cleanup_available,
    }


def snapshot(*routes, required_event=None, mutation_authorized=True):
    return {
        "schema_version": 1,
        "request": {
            "required_claim": "exact-head governed validation",
            "required_event": required_event,
            "require_exact_head": True,
            "mutation_authorized": mutation_authorized,
        },
        "routes": list(routes),
    }


class ActionsExecutionTests(unittest.TestCase):
    def test_missing_dispatch_uses_safe_one_shot(self):
        result = evaluate(
            snapshot(
                route(
                    "dispatch",
                    "DIRECT_WORKFLOW_DISPATCH",
                    available=False,
                    event="workflow_dispatch",
                ),
                route(
                    "one-shot",
                    "ONE_SHOT_WORKFLOW",
                    requires_repository_mutation=True,
                    cleanup_available=True,
                ),
            )
        )
        self.assertEqual(result["status"], "ROUTE_READY")
        self.assertEqual(result["route_kind"], "ONE_SHOT_WORKFLOW")
        self.assertEqual(
            result["handoffs"],
            [
                "repository-mutation",
                "github-actions-observation",
                "repository-mutation:cleanup",
            ],
        )

    def test_required_workflow_dispatch_rejects_push_one_shot(self):
        result = evaluate(
            snapshot(
                route(
                    "dispatch",
                    "DIRECT_WORKFLOW_DISPATCH",
                    available=False,
                    event="workflow_dispatch",
                ),
                route(
                    "one-shot",
                    "ONE_SHOT_WORKFLOW",
                    event="push",
                    requires_repository_mutation=True,
                ),
                required_event="workflow_dispatch",
            )
        )
        self.assertEqual(result["status"], "NO_SAFE_EQUIVALENT_ROUTE")
        one_shot = next(
            item for item in result["rejected_routes"]
            if item["id"] == "one-shot"
        )
        self.assertIn("WRONG_EVENT", one_shot["reasons"])

    def test_existing_trigger_precedes_one_shot(self):
        result = evaluate(
            snapshot(
                route(
                    "existing",
                    "EXISTING_WORKFLOW_TRIGGER",
                    event="pull_request",
                ),
                route(
                    "one-shot",
                    "ONE_SHOT_WORKFLOW",
                    requires_repository_mutation=True,
                ),
            )
        )
        self.assertEqual(result["route_kind"], "EXISTING_WORKFLOW_TRIGGER")

    def test_direct_dispatch_precedes_other_eligible_routes(self):
        result = evaluate(
            snapshot(
                route(
                    "one-shot",
                    "ONE_SHOT_WORKFLOW",
                    requires_repository_mutation=True,
                ),
                route(
                    "dispatch",
                    "DIRECT_WORKFLOW_DISPATCH",
                    event="workflow_dispatch",
                ),
            )
        )
        self.assertEqual(result["route_kind"], "DIRECT_WORKFLOW_DISPATCH")

    def test_one_shot_requires_cleanup_route(self):
        result = evaluate(
            snapshot(
                route(
                    "one-shot",
                    "ONE_SHOT_WORKFLOW",
                    requires_repository_mutation=True,
                    cleanup_available=False,
                )
            )
        )
        self.assertEqual(result["status"], "NO_SAFE_EQUIVALENT_ROUTE")
        self.assertIn(
            "CLEANUP_UNAVAILABLE",
            result["rejected_routes"][0]["reasons"],
        )

    def test_one_shot_requires_mutation_authority(self):
        result = evaluate(
            snapshot(
                route(
                    "one-shot",
                    "ONE_SHOT_WORKFLOW",
                    requires_repository_mutation=True,
                ),
                mutation_authorized=False,
            )
        )
        self.assertEqual(result["status"], "NO_SAFE_EQUIVALENT_ROUTE")
        self.assertIn(
            "MUTATION_NOT_AUTHORIZED",
            result["rejected_routes"][0]["reasons"],
        )

    def test_available_routes_all_unauthorized_report_authority_gate(self):
        result = evaluate(
            snapshot(
                route(
                    "existing",
                    "EXISTING_WORKFLOW_TRIGGER",
                    authorized=False,
                ),
                route(
                    "dispatch",
                    "DIRECT_WORKFLOW_DISPATCH",
                    authorized=False,
                    event="workflow_dispatch",
                ),
            )
        )
        self.assertEqual(result["status"], "NO_AUTHORIZED_ROUTE")

    def test_exact_head_requirement_rejects_non_preserving_route(self):
        result = evaluate(
            snapshot(
                route(
                    "rerun",
                    "RERUN_EXISTING_RUN",
                    preserves_exact_head=False,
                )
            )
        )
        self.assertEqual(result["status"], "NO_SAFE_EQUIVALENT_ROUTE")
        self.assertIn(
            "HEAD_NOT_PRESERVED",
            result["rejected_routes"][0]["reasons"],
        )

    def test_unobservable_route_is_not_equivalent(self):
        result = evaluate(
            snapshot(
                route(
                    "existing",
                    "EXISTING_WORKFLOW_TRIGGER",
                    observable=False,
                )
            )
        )
        self.assertEqual(result["status"], "NO_SAFE_EQUIVALENT_ROUTE")
        self.assertIn(
            "NOT_OBSERVABLE",
            result["rejected_routes"][0]["reasons"],
        )

    def test_route_order_does_not_change_precedence(self):
        direct = route(
            "z-dispatch",
            "DIRECT_WORKFLOW_DISPATCH",
            event="workflow_dispatch",
        )
        existing = route("a-existing", "EXISTING_WORKFLOW_TRIGGER")
        first = evaluate(snapshot(existing, direct))
        second = evaluate(snapshot(direct, existing))
        self.assertEqual(first["route_id"], "z-dispatch")
        self.assertEqual(second["route_id"], "z-dispatch")

    def test_duplicate_route_id_fails_closed(self):
        with self.assertRaises(ActionsExecutionError):
            evaluate(
                snapshot(
                    route("same", "EXISTING_WORKFLOW_TRIGGER"),
                    route(
                        "same",
                        "ONE_SHOT_WORKFLOW",
                        requires_repository_mutation=True,
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
