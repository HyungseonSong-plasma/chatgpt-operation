import unittest

from chatgpt_operation.controller.decisions import DecisionRegistry, GuardOutcome
from chatgpt_operation.controller.issue_planning import plan_admitted_issue
from chatgpt_operation.controller.issue_reasoning import IssueReasoningProposal, compile_guarded_action


class IssueReasoningTests(unittest.TestCase):
    def envelope(self):
        registry=DecisionRegistry.load("automation/samuel/decisions.json")
        return plan_admitted_issue(
            {"work_id":"issue:44","title":"Samuel OS","body":"continue"},
            registry=registry,
        ).envelope

    def test_missing_action_plan_blocks_execution(self):
        proposal=IssueReasoningProposal.from_dict({
            "operation":"analyze","decision_id":None,
            "compatible_with_locked_decisions":True,
            "revision_requested":False,"action_plan":None,
        })
        outcome,plan,_=compile_guarded_action(proposal,self.envelope())
        self.assertEqual(outcome,GuardOutcome.BLOCKED)
        self.assertIsNone(plan)

    def test_conflicting_proposal_cannot_compile_action(self):
        proposal=IssueReasoningProposal.from_dict({
            "operation":"analyze","decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":False,
            "revision_requested":False,
            "action_plan":{
                "schema_version":1,"research_id":"issue:44","stage":"implement",
                "executor":"github_native","payload":{"operation":"COMMENT_ISSUE"},
                "expected_observation":"comment exists",
            },
        })
        outcome,plan,_=compile_guarded_action(proposal,self.envelope())
        self.assertEqual(outcome,GuardOutcome.REJECTED)
        self.assertIsNone(plan)

    def test_compatible_typed_plan_compiles(self):
        proposal=IssueReasoningProposal.from_dict({
            "operation":"analyze","decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":{
                "schema_version":1,"research_id":"issue:44","stage":"implement",
                "executor":"github_native","payload":{"operation":"COMMENT_ISSUE"},
                "expected_observation":"comment exists",
            },
        })
        outcome,plan,_=compile_guarded_action(proposal,self.envelope())
        self.assertEqual(outcome,GuardOutcome.CONTINUE)
        self.assertIsNotNone(plan)


if __name__ == "__main__":
    unittest.main()
