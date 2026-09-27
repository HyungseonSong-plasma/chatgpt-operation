import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.github.native_orchestration import (
    NativeOrchestrationError, dispatch_native_plan,
)


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:44",
        "stage":"implement",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{"number":44,"marker":"<!-- e2e -->","body":"<!-- e2e -->"},
            "preconditions":{"issue_state":"open","comment_present":False},
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":"marker exists",
    })


class NativeBoundaryContractTests(unittest.TestCase):
    @patch("chatgpt_operation.github.native_orchestration.dispatch_and_wait")
    def test_action_identity_is_transport_correlation(self, dispatch):
        p=plan()
        dispatch.return_value={"observation":{
            "status":"MATCHED_TERMINAL","conclusion":"success",
            "matched_run_ids":[123],
        }}
        dispatch_native_plan(p,transport=object(),ref="main")
        kwargs=dispatch.call_args.kwargs
        self.assertEqual(kwargs["correlation_id"],p.idempotency_key)
        self.assertIsNone(kwargs["correlation_input"])
        self.assertEqual(kwargs["correlation_id"],p.idempotency_key)

    @patch("chatgpt_operation.github.native_orchestration.dispatch_and_wait")
    def test_no_match_fails_closed(self, dispatch):
        dispatch.return_value={"observation":{"status":"NO_MATCH"}}
        with self.assertRaisesRegex(NativeOrchestrationError,"NO_MATCH"):
            dispatch_native_plan(plan(),transport=object(),ref="main")

    @patch("chatgpt_operation.github.native_orchestration.dispatch_and_wait")
    def test_ambiguous_match_fails_closed(self, dispatch):
        dispatch.return_value={"observation":{"status":"AMBIGUOUS"}}
        with self.assertRaisesRegex(NativeOrchestrationError,"AMBIGUOUS"):
            dispatch_native_plan(plan(),transport=object(),ref="main")

    @patch("chatgpt_operation.github.native_orchestration.dispatch_and_wait")
    def test_failed_child_fails_closed(self, dispatch):
        dispatch.return_value={"observation":{
            "status":"MATCHED_TERMINAL","conclusion":"failure",
            "matched_run_ids":[123],
        }}
        with self.assertRaisesRegex(NativeOrchestrationError,"failed"):
            dispatch_native_plan(plan(),transport=object(),ref="main")


if __name__ == "__main__":
    unittest.main()
