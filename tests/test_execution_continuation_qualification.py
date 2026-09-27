import unittest
from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.execution_qualification import (
    qualify_execution_continuation, retryable_failure_case,
)
from chatgpt_operation.controller.invariants import ContinuationKind

def failed():
    return ExecutionResult(
        research_id="q", action_id="a"*64, executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.FAILED, observation="temporary postcondition failure",
        retryable=True, details={"provider":"github"},
    )

class ExecutionContinuationQualificationTests(unittest.TestCase):
    def test_retryable_failure_preserves_retry(self):
        q=retryable_failure_case(failed())
        self.assertTrue(q.passed)
        self.assertEqual(q.actual,ContinuationKind.RETRY)
        self.assertTrue(q.retryable)

    def test_repeated_identical_failure_requires_diagnosis(self):
        result=failed()
        q=qualify_execution_continuation(
            case_id="retry-loop-break", result=result,
            expected=ContinuationKind.DIAGNOSE,
            history=[result,result], repeat_limit=3,
        )
        self.assertTrue(q.passed)
        self.assertEqual(q.actual,ContinuationKind.DIAGNOSE)

    def test_wrong_expected_continuation_fails_qualification(self):
        q=qualify_execution_continuation(
            case_id="negative-control", result=failed(),
            expected=ContinuationKind.BLOCKED,
        )
        self.assertFalse(q.passed)
        self.assertEqual(q.actual,ContinuationKind.RETRY)

if __name__=="__main__":
    unittest.main()
