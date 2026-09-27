import unittest

from chatgpt_operation.controller.durable_state import (
    decode_state,
    state_write_request,
)
from chatgpt_operation.controller.research import ResearchState


class DurableStateBoundaryTests(unittest.TestCase):
    def test_new_state_requests_create_and_round_trips(self):
        state = ResearchState("issue:44", "Samuel")
        state.revision = 1
        request = state_write_request([], state)
        self.assertEqual(request["method"], "POST")
        self.assertIsNone(request["comment_id"])
        self.assertEqual(request["expected_revision"], 1)
        persisted = decode_state(request["body"])
        self.assertEqual(persisted.research_id, "issue:44")
        self.assertEqual(persisted.revision, 1)

    def test_existing_state_requests_update(self):
        state = ResearchState("issue:44", "Samuel")
        state.revision = 1
        first = state_write_request([], state)
        comments = [{"id": 123, "body": first["body"]}]
        state.revision = 2
        request = state_write_request(comments, state)
        self.assertEqual(request["method"], "PATCH")
        self.assertEqual(request["comment_id"], 123)
        self.assertEqual(request["expected_previous_revision"], 1)
        self.assertEqual(request["expected_revision"], 2)


if __name__ == "__main__":
    unittest.main()
