import unittest

from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.controller.execution import (
    ExecutionResult,
    ExecutionResultError,
    ExecutionStatus,
    require_execution_provenance,
)


def result(provenance):
    return ExecutionResult(
        research_id="r",
        action_id="a"*64,
        executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.PASS,
        observation="verified",
        details={"provenance":provenance},
    )


class ExecutionProvenanceTests(unittest.TestCase):
    def provenance(self, **overrides):
        value={
            "schema_version":1,
            "workflow_run_id":99,
            "run_attempt":1,
            "head_sha":"b"*40,
            "action_id":"a"*64,
        }
        value.update(overrides)
        return value

    def test_valid_provenance_binds_action_and_run(self):
        p=require_execution_provenance(result(self.provenance()),workflow_run_id=99)
        self.assertEqual(p.workflow_run_id,99)
        self.assertEqual(p.action_id,"a"*64)

    def test_foreign_action_provenance_is_rejected(self):
        with self.assertRaisesRegex(ExecutionResultError,"action_id mismatch"):
            require_execution_provenance(result(self.provenance(action_id="b"*64)))

    def test_foreign_workflow_run_is_rejected(self):
        with self.assertRaisesRegex(ExecutionResultError,"workflow_run_id mismatch"):
            require_execution_provenance(result(self.provenance()),workflow_run_id=100)


if __name__ == "__main__":
    unittest.main()
