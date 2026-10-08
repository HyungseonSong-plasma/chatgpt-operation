from __future__ import annotations

import unittest
from unittest.mock import patch

from chatgpt_operation.repository.branch_delete import BranchDeleteError, delete_branch


SHA = "a" * 40
OTHER = "b" * 40


class BranchDeleteTests(unittest.TestCase):
    def test_exact_sha_delete_and_readback(self):
        with patch(
            "chatgpt_operation.repository.branch_delete._request",
            side_effect=[{"object": {"sha": SHA}}, None, None],
        ) as request:
            result = delete_branch(repository="o/r", token="t", branch="old", expected_sha=SHA)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(request.call_args_list[1].args[2], "DELETE")

    def test_absent_is_idempotent_noop(self):
        with patch("chatgpt_operation.repository.branch_delete._request", return_value=None):
            result = delete_branch(repository="o/r", token="t", branch="old", expected_sha=SHA)
        self.assertEqual(result.status, "NO_MUTATION_NEEDED")

    def test_stale_sha_hard_stops_before_delete(self):
        with patch(
            "chatgpt_operation.repository.branch_delete._request",
            return_value={"object": {"sha": OTHER}},
        ) as request:
            with self.assertRaisesRegex(BranchDeleteError, "stale branch identity"):
                delete_branch(repository="o/r", token="t", branch="old", expected_sha=SHA)
        self.assertEqual(request.call_count, 1)

    def test_main_is_denied(self):
        with self.assertRaisesRegex(BranchDeleteError, "default branch deletion is denied"):
            delete_branch(repository="o/r", token="t", branch="main", expected_sha=SHA)

    def test_post_delete_presence_hard_stops(self):
        with patch(
            "chatgpt_operation.repository.branch_delete._request",
            side_effect=[{"object": {"sha": SHA}}, None, {"object": {"sha": SHA}}],
        ):
            with self.assertRaisesRegex(BranchDeleteError, "post-delete verification mismatch"):
                delete_branch(repository="o/r", token="t", branch="old", expected_sha=SHA)


if __name__ == "__main__":
    unittest.main()
