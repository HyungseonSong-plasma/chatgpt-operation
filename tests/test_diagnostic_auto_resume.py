import unittest
from chatgpt_operation.controller.diagnostic import resume_resolved_action
from chatgpt_operation.controller.research import ResearchState


class DiagnosticAutoResumeContract(unittest.TestCase):
    def test_resolved_owned_action_returns_to_pending(self):
        action_id="a"
        state=ResearchState("r","finish",
            diagnostic_recoveries={action_id:{"status":"resolved"}},
            action_queue={action_id:{"status":"suspended","plan":{
                "schema_version":1,"research_id":"r","stage":"execute",
                "executor":"github_native","payload":{"action":"comment_issue",
                "repository":"o/r","target":{"issue_number":1},
                "preconditions":{"state":"open"},
                "desired_postcondition":{"comment_present":True}},
                "expected_observation":"verified","decision_risk":None}}})
        plan=resume_resolved_action(state,action_id)
        self.assertEqual(plan.idempotency_key,action_id)
        self.assertEqual(state.action_queue[action_id]["status"],"pending")
