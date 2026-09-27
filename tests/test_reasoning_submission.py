import unittest
from chatgpt_operation.controller.reasoning_submission import (
    ReasoningSubmission,ReasoningSubmissionError,encode_submission,decode_submission,select_submission,
)
from chatgpt_operation.controller.issue_reasoning import IssueReasoningProposal

class ReasoningSubmissionTests(unittest.TestCase):
    def submission(self):
        return ReasoningSubmission("issue:44",IssueReasoningProposal("analyze",None,True,False,None))

    def test_round_trip(self):
        x=self.submission()
        self.assertEqual(decode_submission(encode_submission(x)),x)

    def test_duplicate_is_ambiguous(self):
        body=encode_submission(self.submission())
        with self.assertRaises(ReasoningSubmissionError):
            select_submission([{"body":body},{"body":body}],"issue:44")

    def test_wrong_work_is_not_selected(self):
        body=encode_submission(self.submission())
        self.assertIsNone(select_submission([{"body":body}],"issue:45"))

    def test_round_trip_preserves_tilde_fence_inside_action_plan_content(self):
        proposal=IssueReasoningProposal(
            "analyze",
            "github_execution_authority",
            True,
            False,
            {
                "schema_version":1,
                "research_id":"issue:44",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":"o/r",
                    "resource":"file",
                    "action":"create",
                    "target":{"path":"x.py","branch":"issue-x"},
                    "expected":{"absent":True},
                    "desired":{"content":'marker="~~~json"\\nclosing="~~~"\\n'},
                    "commit_message":"create x",
                },
                "expected_observation":"file exists",
            },
        )
        original=ReasoningSubmission("issue:44",proposal)
        restored=decode_submission(encode_submission(original))
        self.assertEqual(
            restored.proposal.action_plan["payload"]["desired"]["content"],
            proposal.action_plan["payload"]["desired"]["content"],
        )

if __name__=="__main__":
    unittest.main()
