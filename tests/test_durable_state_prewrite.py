import copy
import unittest

from chatgpt_operation.controller.durable_state import (
    DurableStateError,
    encode_state,
    state_write_request,
    validate_state_write_precondition,
)
from chatgpt_operation.controller.research import ResearchState


class DurableStatePrewriteTests(unittest.TestCase):
    def comments(self, state, comment_id=44):
        return [{"id":comment_id,"body":encode_state(state)}]

    def test_fresh_update_precondition_passes(self):
        current=ResearchState("r","objective",revision=2)
        proposed=copy.deepcopy(current); proposed.revision=3
        comments=self.comments(current)
        request=state_write_request(comments,proposed)
        validate_state_write_precondition(comments,request)

    def test_stale_update_is_rejected_after_authoritative_reread(self):
        current=ResearchState("r","objective",revision=2)
        proposed=copy.deepcopy(current); proposed.revision=3
        request=state_write_request(self.comments(current),proposed)
        newer=copy.deepcopy(current); newer.revision=3
        with self.assertRaisesRegex(DurableStateError,"stale durable state precondition"):
            validate_state_write_precondition(self.comments(newer),request)

    def test_create_is_rejected_if_state_appeared_after_prepare(self):
        proposed=ResearchState("r","objective",revision=1)
        request=state_write_request([],proposed)
        appeared=ResearchState("r","objective",revision=1)
        with self.assertRaisesRegex(DurableStateError,"create precondition"):
            validate_state_write_precondition(self.comments(appeared),request)

    def test_tampered_payload_revision_is_rejected(self):
        current=ResearchState("r","objective",revision=2)
        proposed=copy.deepcopy(current); proposed.revision=3
        comments=self.comments(current)
        request=state_write_request(comments,proposed)
        request["expected_revision"]=4
        with self.assertRaisesRegex(DurableStateError,"payload mismatch"):
            validate_state_write_precondition(comments,request)


if __name__ == "__main__":
    unittest.main()
