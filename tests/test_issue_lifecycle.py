import unittest
from dataclasses import asdict
from chatgpt_operation.controller.issue_ingestion import (
    AdmittedIssueWork, AdmissionError, transition_issue_status,
)

class IssueLifecycleTests(unittest.TestCase):
    def test_reasoning_required_is_controller_lifecycle(self):
        work={"issue:44":asdict(AdmittedIssueWork("issue:44",44,"t","b","u"))}
        updated=transition_issue_status(work,"issue:44","reasoning_required")
        self.assertEqual(updated["issue:44"]["status"],"reasoning_required")
        self.assertEqual(work["issue:44"]["status"],"admitted")

    def test_unknown_lifecycle_fails_closed(self):
        work={"issue:44":asdict(AdmittedIssueWork("issue:44",44,"t","b","u"))}
        with self.assertRaises(AdmissionError):
            transition_issue_status(work,"issue:44","invented")

if __name__=="__main__":
    unittest.main()
