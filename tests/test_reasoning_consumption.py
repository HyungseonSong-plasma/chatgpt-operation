import unittest
from dataclasses import asdict
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.issue_ingestion import AdmittedIssueWork
from chatgpt_operation.controller.issue_reasoning import IssueReasoningProposal
from chatgpt_operation.controller.reasoning_submission import ReasoningSubmission,encode_submission
from chatgpt_operation.controller.reasoning_consumption import consume_reasoning_submission
from chatgpt_operation.controller.research import ResearchState

class ReasoningConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.work={"issue:44":asdict(AdmittedIssueWork("issue:44",44,"Samuel OS","body","u",status="reasoning_required"))}
        self.registry=DecisionRegistry.load("automation/samuel/decisions.json")
        self.state=ResearchState("issue:44","Samuel OS")

    def test_wait_without_submission(self):
        x=consume_reasoning_submission([],self.work,"issue:44",registry=self.registry,state=self.state)
        self.assertEqual(x.outcome,"reasoning_required")

    def test_guarded_plan_enters_existing_queue(self):
        p=IssueReasoningProposal("analyze","github_execution_authority",True,False,{
            "schema_version":1,"research_id":"issue:44","stage":"implement",
            "executor":"github_native","payload":{"operation":"COMMENT_ISSUE"},
            "expected_observation":"comment exists",
        })
        body=encode_submission(ReasoningSubmission("issue:44",p))
        x=consume_reasoning_submission([{"body":body}],self.work,"issue:44",registry=self.registry,state=self.state)
        self.assertEqual(x.outcome,"planned")
        self.assertEqual(x.work["issue:44"]["status"],"planned")
        self.assertIn(x.action_id,x.state.action_queue)

if __name__=="__main__":
    unittest.main()
