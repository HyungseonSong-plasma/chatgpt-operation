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

    def test_analyze_without_action_plan_preserves_continue(self):
        proposal=IssueReasoningProposal.from_dict({
            "operation":"analyze","decision_id":None,
            "compatible_with_locked_decisions":True,
            "revision_requested":False,"action_plan":None,
        })
        outcome,plan,_=compile_guarded_action(proposal,self.envelope())
        self.assertEqual(outcome,GuardOutcome.CONTINUE)
        self.assertIsNone(plan)

    def test_implement_gap_without_action_plan_blocks_execution(self):
        proposal=IssueReasoningProposal.from_dict({
            "operation":"implement_gap","decision_id":None,
            "compatible_with_locked_decisions":True,
            "revision_requested":False,"action_plan":None,
        })
        envelope=self.envelope()
        from dataclasses import replace
        envelope=replace(envelope,implementation_gaps=("missing:test-capability",))
        outcome,plan,_=compile_guarded_action(proposal,envelope)
        self.assertEqual(outcome,GuardOutcome.BLOCKED)
        self.assertIsNone(plan)

    def test_typed_blocker_requires_closed_world_alternative_search(self):
        proposal=IssueReasoningProposal.from_dict({
            "operation":"propose_revision",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":False,
            "revision_requested":True,
            "action_plan":None,
            "blocker":{
                "capability":"workflow_file_mutation",
                "alternatives_considered":["existing_scheduled_runtime"],
                "exhausted":False,
            },
        })
        self.assertEqual(proposal.blocker["capability"],"workflow_file_mutation")
        self.assertEqual(
            proposal.blocker["alternatives_considered"],
            ["existing_scheduled_runtime"],
        )
        with self.assertRaisesRegex(ValueError,"invalid blocker schema"):
            IssueReasoningProposal.from_dict({
                "operation":"analyze",
                "decision_id":None,
                "compatible_with_locked_decisions":True,
                "revision_requested":False,
                "action_plan":None,
                "blocker":{"capability":"x"},
            })

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
