import copy
import unittest

from chatgpt_operation.controller.durable_state import (
    encode_state,
    state_write_request,
)
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.state_persistence import (
    StatePersistenceError,
    persist_state_write,
)


class FakeTransport:
    def __init__(self, comments=None, *, corrupt_readback=False):
        self.comments=list(comments or [])
        self.calls=[]
        self.corrupt_readback=corrupt_readback

    def get(self, path, *, query=None):
        self.calls.append(("GET",path,query))
        if self.corrupt_readback and len([c for c in self.calls if c[0]=="GET"]) > 1:
            return []
        return copy.deepcopy(self.comments)

    def request(self, method, path, *, payload=None):
        self.calls.append((method,path,payload))
        if method=="POST":
            item={"id":101,"body":payload["body"]}
            self.comments.append(item)
            return 201,copy.deepcopy(item)
        if method=="PATCH":
            comment_id=int(path.rsplit("/",1)[-1])
            for item in self.comments:
                if item["id"]==comment_id:
                    item["body"]=payload["body"]
                    return 200,copy.deepcopy(item)
            return 404,{"message":"not found"}
        raise AssertionError(method)


def state(revision):
    return ResearchState(
        "issue:44",
        "controller qualification",
        stage=ResearchStage.DEFINE_PROBLEM,
        revision=revision,
    )


class StatePersistenceTests(unittest.TestCase):
    def test_create_validates_writes_and_reads_back(self):
        proposed=state(1)
        request=state_write_request([],proposed)
        transport=FakeTransport()

        result=persist_state_write(
            transport,issue_number=44,request=request
        )

        self.assertEqual(result.revision,1)
        self.assertEqual(result.method,"POST")
        self.assertEqual(result.comment_id,101)
        self.assertEqual(
            [call[0] for call in transport.calls],
            ["GET","POST","GET"],
        )

    def test_update_validates_writes_and_reads_back(self):
        current=state(1)
        comments=[{"id":7,"body":encode_state(current)}]
        proposed=copy.deepcopy(current)
        proposed.revision=2
        request=state_write_request(comments,proposed)
        transport=FakeTransport(comments)

        result=persist_state_write(
            transport,issue_number=44,request=request
        )

        self.assertEqual(result.revision,2)
        self.assertEqual(result.method,"PATCH")
        self.assertEqual(result.comment_id,7)
        self.assertEqual(transport.calls[1][1],"/issues/comments/7")

    def test_stale_precondition_blocks_before_mutation(self):
        original=state(1)
        comments=[{"id":7,"body":encode_state(original)}]
        proposed=copy.deepcopy(original)
        proposed.revision=2
        request=state_write_request(comments,proposed)

        advanced=copy.deepcopy(original)
        advanced.revision=3
        transport=FakeTransport([{"id":7,"body":encode_state(advanced)}])

        with self.assertRaisesRegex(Exception,"stale durable state precondition"):
            persist_state_write(
                transport,issue_number=44,request=request
            )
        self.assertEqual([c[0] for c in transport.calls],["GET"])

    def test_readback_mismatch_fails_closed(self):
        proposed=state(1)
        request=state_write_request([],proposed)
        transport=FakeTransport(corrupt_readback=True)

        with self.assertRaisesRegex(
            StatePersistenceError,"disappeared after write"
        ):
            persist_state_write(
                transport,issue_number=44,request=request
            )


if __name__=="__main__":
    unittest.main()
