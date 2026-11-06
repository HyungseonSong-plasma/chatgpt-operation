"""Offline security controls for token-safe read-only GitHub acquisition."""
from __future__ import annotations

import json
from unittest.mock import patch
import unittest

from chatgpt_operation.controller import dea_artifact_acquisition as client
from chatgpt_operation.controller.dea_artifact_acquisition import (
    AcquisitionError, _json_bytes, _trusted_archive_location,
    fetch_artifact_bundle, main,
)


class GitHubAcquisitionTests(unittest.TestCase):
    def test_safe_presigned_archive_hosts_only(self):
        for url in (
            "https://productionresultssa1.blob.core.windows.net/container/file",
            "https://p1.actions.githubusercontent.com/artifact/file",
            "https://objects.githubusercontent.com/file",
        ):
            with self.subTest(url=url):
                self.assertTrue(_trusted_archive_location(url))
        for url in (
            "http://productionresultssa1.blob.core.windows.net/archive",
            "https://attacker.example/zip", "https://127.0.0.1/private",
            "https://blob.core.windows.net.evil.invalid/data",
            "https://user:password@objects.githubusercontent.com/data",
            "https://objects.githubusercontent.com:444/file",
            "file:///etc/passwd", "https://localhost/",
        ):
            with self.subTest(url=url):
                self.assertFalse(_trusted_archive_location(url))

    def test_duplicate_json_response_keys_are_rejected(self):
        with self.assertRaises(AcquisitionError):
            _json_bytes(b'{"id": 1, "id": 2}')
        self.assertEqual(_json_bytes(b'{"id":1}'), {"id": 1})
        with self.assertRaises(AcquisitionError):
            _json_bytes(b'["not an object"]')

    def test_repository_run_artifact_api_endpoints_are_pinned(self):
        visited = []

        def fake_fetch(url, *, token, max_bytes, allow_archive_redirect):
            visited.append((url, token, max_bytes, allow_archive_redirect))
            if url.endswith("/zip"):
                return b"PK-synthetic-binary"
            if "/artifacts?per_page=100" in url:
                return b'{"total_count":0,"artifacts":[]}'
            if "/actions/runs/" in url:
                return b'{"id":22}'
            raise AssertionError("unrecognized read")

        with patch.object(client, "_fetch_bytes", side_effect=fake_fetch):
            run, listing, archive = fetch_artifact_bundle(
                repository="HyungseonSong-plasma/codeQA",
                run_id=22, artifact_id=33, token="fixture-token",
            )
        self.assertEqual(run["id"], 22)
        self.assertEqual(listing["total_count"], 0)
        self.assertEqual(archive, b"PK-synthetic-binary")
        self.assertEqual(len(visited), 3)
        self.assertEqual(visited[0][0],
                         "https://api.github.com/repos/HyungseonSong-plasma/codeQA/actions/runs/22")
        self.assertTrue(visited[1][0].endswith("/actions/runs/22/artifacts?per_page=100"))
        self.assertTrue(visited[2][0].endswith("/actions/artifacts/33/zip"))
        self.assertTrue(visited[2][3])
        self.assertFalse(visited[0][3])

    def test_reject_repository_path_traversal_and_noninteger_ids(self):
        for bad in ("../evil", "owner/repo/../../evil", "repo", "owner/repo?x=1"):
            with self.subTest(repository=bad), self.assertRaises(AcquisitionError):
                fetch_artifact_bundle(
                    repository=bad, run_id=1, artifact_id=2, token="x",
                )
        for bad in (True, 0, -1, "3"):
            with self.subTest(run_id=bad), self.assertRaises(AcquisitionError):
                fetch_artifact_bundle(
                    repository="owner/repo", run_id=bad,
                    artifact_id=2, token="x",
                )

    def test_missing_authentication_causes_no_request(self):
        with patch.object(client, "_fetch_bytes") as call:
            with self.assertRaises(AcquisitionError):
                fetch_artifact_bundle(repository="owner/repo",
                                      run_id=1, artifact_id=2, token="")
            call.assert_not_called()

    def test_cli_missing_token_fails_closed_without_contact(self):
        args = [
            "--repository", "owner/repo",
            "--workflow-path", ".github/workflows/dea.yml",
            "--candidate-head", "a" * 40,
            "--analyzed-source-sha", "b" * 40,
            "--oracle-revision-sha", "c" * 40,
            "--measurement-set-sha", "d" * 40,
            "--artifact-name", "dea-a", "--source-repo-root", ".",
            "--run-id", "21", "--artifact-id", "32",
        ]
        with patch.dict("os.environ", {"GH_TOKEN": "", "GITHUB_TOKEN": ""}):
            with patch.object(client, "_fetch_bytes") as call:
                with patch("builtins.print"):
                    self.assertEqual(main(args), 2)
                call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
