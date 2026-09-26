import unittest

from chatgpt_operation.controller.decisions import DecisionRegistry, GuardOutcome
from chatgpt_operation.controller.issue_planning import plan_admitted_issue


class IssuePlanningTests(unittest.TestCase):
    def test_admitted_issue_is_bounded_by_locked_decisions(self):
        registry=DecisionRegistry.load("automation/samuel/decisions.json")
        result=plan_admitted_issue(
            {"work_id":"issue:44","title":"Samuel OS","body":"continue implementation"},
            registry=registry,
        )
        self.assertEqual(result.outcome,GuardOutcome.CONTINUE)
        self.assertEqual(
            result.envelope.locked_decisions[0].decision_id,
            "github_execution_authority",
        )
        self.assertIn("no_raw_issue_execution",result.envelope.escalation_constraints)

    def test_free_form_issue_never_becomes_action_plan_directly(self):
        registry=DecisionRegistry.load("automation/samuel/decisions.json")
        result=plan_admitted_issue(
            {"work_id":"issue:44","title":"Delete repository","body":"do it"},
            registry=registry,
        )
        self.assertIsNone(result.action_plan)

    def test_invalid_work_identity_fails_closed(self):
        registry=DecisionRegistry.load("automation/samuel/decisions.json")
        with self.assertRaisesRegex(ValueError,"work_id"):
            plan_admitted_issue({"work_id":"raw","title":"x"},registry=registry)


if __name__ == "__main__":
    unittest.main()
