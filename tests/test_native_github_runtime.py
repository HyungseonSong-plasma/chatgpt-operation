import unittest

from chatgpt_operation.github.native_executor import NativeGitHubAction
from chatgpt_operation.github.native_runtime import GitHubNativeTransport


class FakeTransport(GitHubNativeTransport):
    def __init__(self, responses):
        super().__init__(
            "HyungseonSong-plasma/chatgpt-operation",
            "token",
        )
        self.responses=list(responses)
        self.calls=[]

    def _call(self, method, path, payload=None):
        self.calls.append((method,path,payload))
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


class NativeGitHubRuntimeMergeTests(unittest.TestCase):
    def target(self):
        return {
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "number":136,
            "expected_head_sha":"a"*40,
        }

    def test_check_runs_supply_ci_success_without_classic_statuses(self):
        transport=FakeTransport([
            {
                "merged":False,
                "mergeable":True,
                "head":{"sha":"a"*40},
            },
            {"state":"pending","total_count":0,"statuses":[]},
            {
                "check_runs":[
                    {"status":"completed","conclusion":"success"},
                    {"status":"completed","conclusion":"success"},
                ]
            },
        ])
        state=transport.read_state(NativeGitHubAction.MERGE_PR,self.target())
        self.assertEqual(state["ci"],"success")
        self.assertEqual(len(transport.calls),3)
        self.assertIn("/check-runs?filter=latest&per_page=100",transport.calls[2][1])

    def test_trusted_validation_status_is_authoritative_for_bot_pr(self):
        transport=FakeTransport([
            {
                "merged":False,
                "mergeable":True,
                "head":{"sha":"b"*40},
            },
            {
                "state":"success",
                "total_count":1,
                "statuses":[
                    {
                        "context":"samuel/trusted-validation",
                        "state":"success",
                    }
                ],
            },
        ])
        state=transport.read_state(NativeGitHubAction.MERGE_PR,self.target())
        self.assertEqual(state["ci"],"success")
        self.assertEqual(len(transport.calls),2)

    def test_incomplete_check_run_keeps_merge_pending(self):
        transport=FakeTransport([
            {
                "merged":False,
                "mergeable":True,
                "head":{"sha":"c"*40},
            },
            {"state":"pending","total_count":0,"statuses":[]},
            {"check_runs":[{"status":"in_progress","conclusion":None}]},
        ])
        state=transport.read_state(NativeGitHubAction.MERGE_PR,self.target())
        self.assertEqual(state["ci"],"pending")


class NativeGitHubRuntimeCreatePrTests(unittest.TestCase):
    def target(self):
        return {
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "head":"samuel/issues-24-43",
            "base":"main",
            "title":"Telemetry maintenance",
            "body":"Closes #24 and #43",
        }

    def test_read_state_reports_absent_pr(self):
        transport=FakeTransport([[]])
        state=transport.read_state(
            NativeGitHubAction.CREATE_PR,self.target()
        )
        self.assertEqual(state,{"pr_present":False})
        method,path,_=transport.calls[0]
        self.assertEqual(method,"GET")
        self.assertIn("head=HyungseonSong-plasma%3Asamuel%2Fissues-24-43",path)
        self.assertIn("base=main",path)

    def test_read_state_reports_exact_open_pr(self):
        transport=FakeTransport([[
            {
                "number":130,
                "head":{"sha":"a"*40},
                "base":{"ref":"main"},
            }
        ]])
        state=transport.read_state(
            NativeGitHubAction.CREATE_PR,self.target()
        )
        self.assertEqual(
            state,
            {
                "pr_present":True,
                "pr_number":130,
                "head_sha":"a"*40,
                "base":"main",
            },
        )

    def test_mutate_creates_pr_with_bounded_fields(self):
        transport=FakeTransport([{"number":130}])
        result=transport.mutate(
            NativeGitHubAction.CREATE_PR,self.target()
        )
        self.assertEqual(result["number"],130)
        method,path,payload=transport.calls[0]
        self.assertEqual(method,"POST")
        self.assertEqual(
            path,
            "/repos/HyungseonSong-plasma/chatgpt-operation/pulls",
        )
        self.assertEqual(
            set(payload),
            {"head","base","title","body"},
        )


class NativeGitHubRuntimeDispatchWorkflowTests(unittest.TestCase):
    def target(self):
        return {
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "workflow":"ci.yml",
            "ref":"samuel/issues-24-43-weekly-maintenance-v2",
            "expected_head_sha":"d"*40,
        }

    def test_read_state_requires_exact_head_workflow_dispatch(self):
        transport=FakeTransport([
            {"commit":{"sha":"d"*40}},
            {"id":123},
            {"workflow_runs":[
                {"id":91,"head_sha":"c"*40},
                {"id":92,"head_sha":"d"*40},
            ]},
        ])
        state=transport.read_state(
            NativeGitHubAction.DISPATCH_WORKFLOW,self.target()
        )
        self.assertEqual(
            state,
            {"head_sha":"d"*40,"ci_started":True},
        )
        self.assertIn(
            "/actions/workflows/123/runs?event=workflow_dispatch",
            transport.calls[2][1],
        )

    def test_read_state_keeps_stale_branch_head_visible(self):
        transport=FakeTransport([
            {"commit":{"sha":"e"*40}},
            {"id":123},
            {"workflow_runs":[]},
        ])
        state=transport.read_state(
            NativeGitHubAction.DISPATCH_WORKFLOW,self.target()
        )
        self.assertEqual(
            state,
            {"head_sha":"e"*40,"ci_started":False},
        )

    def test_mutate_dispatches_and_waits_until_exact_head_is_visible(self):
        transport=FakeTransport([
            {},
            {"commit":{"sha":"d"*40}},
            {"id":123},
            {"workflow_runs":[{"id":92,"head_sha":"d"*40}]},
        ])
        result=transport.mutate(
            NativeGitHubAction.DISPATCH_WORKFLOW,self.target()
        )
        self.assertTrue(result["accepted"])
        self.assertTrue(result["verified_visible"])
        self.assertEqual(result["attempts"],1)
        method,path,payload=transport.calls[0]
        self.assertEqual(method,"POST")
        self.assertEqual(
            path,
            "/repos/HyungseonSong-plasma/chatgpt-operation/actions/workflows/ci.yml/dispatches",
        )
        self.assertEqual(
            payload,
            {"ref":"samuel/issues-24-43-weekly-maintenance-v2"},
        )


if __name__=="__main__":
    unittest.main()
