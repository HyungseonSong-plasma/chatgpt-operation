import unittest
from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.diagnostic import recovery_authorization
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.github.execution_kernel import ExecutionKernel, ExecutionKernelError, native_runtime_provider


def plan():
    return ActionPlan.from_dict({"schema_version":1,"research_id":"r","stage":"execute",
      "executor":"github_native","payload":{"action":"comment_issue","repository":"o/r",
      "target":{"issue_number":44},"preconditions":{"state":"open"},
      "desired_postcondition":{"comment_present":True}},"expected_observation":"verified"})


class T:
    def read_state(self,*a): return {}
    def mutate(self,*a): return {}


def test_kernel_rejects_provider_not_bound_by_recovery_authorization():
    p=plan()
    s=ResearchState("r","finish",diagnostic_recoveries={p.idempotency_key:{
      "status":"open","root_cause":"x","corrective_action":"retry",
      "corrective_provider":"workflow-provider",
      "source_plan":{"schema_version":1,"research_id":"r","stage":"execute",
      "executor":"github_native","payload":p.payload,"expected_observation":"verified",
      "decision_risk":None}}})
    auth=recovery_authorization(s,p.idempotency_key)
    kernel=ExecutionKernel([native_runtime_provider("native-provider",T())],state=s)
    try:
        kernel.execute(p,recovery_authorization=auth)
    except ExecutionKernelError as exc:
        assert "authorized corrective provider" in str(exc)
    else:
        raise AssertionError("mismatched corrective provider must fail closed")
