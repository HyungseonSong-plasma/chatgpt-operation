import copy
import unittest

from chatgpt_operation.controller.durable_state import (
    encode_state,
    load_state_comment,
    state_write_request,
)
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.state_persistence import (
    StatePersistenceError,
    persist_state_write,
)


class FakeTransport:
    def __init__(
        self, comments=None, *, corrupt_readback=False,
        race_readback=None, lose_ack=False,
    ):
        self.comments=list(comments or [])
        self.calls=[]
        self.corrupt_readback=corrupt_readback
        self.race_readback=race_readback
        self.lose_ack=lose_ack

    def get(self, path, *, query=None):
        self.calls.append(("GET",path,query))
        if self.corrupt_readback and len([c for c in self.calls if c[0]=="GET"]) > 1:
            return []
        if self.race_readback is not None and len(
            [c for c in self.calls if c[0]=="GET"]
        ) > 1:
            # Simulate a competing GitHub Issue comment PATCH happening
            # between our accepted write and its authoritative readback.
            self.comments=copy.deepcopy(self.race_readback)
        return copy.deepcopy(self.comments)

    def request(self, method, path, *, payload=None):
        self.calls.append((method,path,payload))
        if method=="POST":
            item={"id":101,"body":payload["body"]}
            self.comments.append(item)
            if self.lose_ack:
                raise TimeoutError("simulated response lost after accepted POST")
            return 201,copy.deepcopy(item)
        if method=="PATCH":
            comment_id=int(path.rsplit("/",1)[-1])
            for item in self.comments:
                if item["id"]==comment_id:
                    item["body"]=payload["body"]
                    if self.lose_ack:
                        raise TimeoutError("simulated response lost after accepted PATCH")
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

    def test_same_revision_different_payload_is_not_accepted_as_our_write(self):
        current=state(1)
        comments=[{"id":7,"body":encode_state(current)}]
        ours=copy.deepcopy(current)
        ours.revision=2
        ours.objective="accepted writer A"
        competing=copy.deepcopy(current)
        competing.revision=2
        competing.objective="overwriting writer B"
        transport=FakeTransport(
            comments,
            race_readback=[{"id":7,"body":encode_state(competing)}],
        )
        with self.assertRaisesRegex(
            StatePersistenceError,"readback content mismatch"
        ):
            persist_state_write(
                transport,
                issue_number=44,
                request=state_write_request(comments,ours),
            )
        self.assertEqual(
            [c[0] for c in transport.calls],
            ["GET","PATCH","GET"],
        )
        self.assertEqual(
            load_state_comment(transport.comments).objective,
            "overwriting writer B",
        )

    def test_lost_ack_after_post_recovers_existing_comment_without_retry(self):
        proposed=state(1)
        transport=FakeTransport(lose_ack=True)
        with self.assertRaisesRegex(TimeoutError,"accepted POST"):
            persist_state_write(
                transport,
                issue_number=44,
                request=state_write_request([],proposed),
            )
        recovered=load_state_comment(transport.get("/issues/44/comments"))
        self.assertEqual(recovered,proposed)
        self.assertEqual(len(transport.comments),1)
        # Do not issue a second POST; its durable evidence is already present.
        self.assertEqual([c[0] for c in transport.calls],["GET","POST","GET"])

    def test_lost_ack_after_patch_recovers_exact_advanced_payload(self):
        before=state(1)
        comments=[{"id":7,"body":encode_state(before)}]
        proposed=copy.deepcopy(before)
        proposed.revision=2
        proposed.objective="already committed"
        transport=FakeTransport(comments,lose_ack=True)
        with self.assertRaisesRegex(TimeoutError,"accepted PATCH"):
            persist_state_write(
                transport,
                issue_number=44,
                request=state_write_request(comments,proposed),
            )
        recovered=load_state_comment(transport.get("/issues/44/comments"))
        self.assertEqual(recovered,proposed)
        self.assertEqual(len(transport.comments),1)
        self.assertEqual([c[0] for c in transport.calls],["GET","PATCH","GET"])

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
