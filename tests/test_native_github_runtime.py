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


if __name__=="__main__":
    unittest.main()
