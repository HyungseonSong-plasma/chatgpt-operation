"""Read-only GH API preflight: authenticated metadata never grants force."""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from chatgpt_operation.controller import dea_environment_preflight_cli as cli
from test_dea_environment_preflight import ENV, BRANCHES, RULES


def mock_gh(argv, **kwargs):
    assert argv[:4] == ["gh", "api", "--method", "GET"], argv
    endpoint = argv[4]
    if endpoint.endswith("/environments/dea-human-break-glass"):
        value = ENV
    elif "deployment-branch-policies?per_page=100" in endpoint:
        value = BRANCHES
    elif endpoint.endswith("/rulesets?per_page=100"):
        value = [{"id": 77, "name": "dea-main-protection"}]
    elif endpoint.endswith("/rulesets/77"):
        value = {"id": 77, **RULES[0]}
    else:
        raise AssertionError("unexpected GH endpoint " + endpoint)
    return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b"")


class EnvironmentReadbackCLITests(unittest.TestCase):
    def test_only_get_and_approval_is_never_granted(self):
        with patch.object(cli.subprocess, "run", side_effect=mock_gh) as mock:
            result = cli.read_live_preflight({"human-operator"})
        self.assertEqual(result["status"], "CONFIGURATION_SNAPSHOT_MATCH")
        self.assertFalse(result["human_only_break_glass_active"])
        self.assertEqual(mock.call_count, 4)
        for call in mock.call_args_list:
            self.assertEqual(call.args[0][2:4], ["--method", "GET"])

    def test_missing_ruleset_fails_closed(self):
        def no_ruleset(argv, **kwargs):
            if argv[4].endswith("/rulesets?per_page=100"):
                return subprocess.CompletedProcess(argv, 0, b"[]", b"")
            return mock_gh(argv, **kwargs)
        with patch.object(cli.subprocess, "run", side_effect=no_ruleset):
            result = cli.read_live_preflight({"human-operator"})
        self.assertEqual(result["status"], "CONFIGURATION_INCOMPLETE")
        self.assertIn("MAIN_RULESET_WITH_CI_AND_PR_PROTECTION_NOT_VERIFIED",
                      result["missing_protections"])

    def test_nonhuman_or_fake_login_denied_before_api_calls(self):
        with patch.object(cli.subprocess, "run") as process:
            for logins in ({"someone[bot]"}, {"bad space"}, set()):
                with self.subTest(logins=logins):
                    with self.assertRaises(cli.PreflightReadError):
                        cli.read_live_preflight(logins)
            process.assert_not_called()

    def test_disallowed_url_or_mutation_endpoint_denied(self):
        with patch.object(cli.subprocess, "run") as process:
            for path in (
                "repos/other/repository/rulesets",
                "repos/HyungseonSong-plasma/chatgpt-operation/actions/workflows",
                "repos/HyungseonSong-plasma/chatgpt-operation/rulesets/77/../99",
            ):
                with self.subTest(path=path), self.assertRaises(cli.PreflightReadError):
                    cli._gh_get(path)
            process.assert_not_called()

    def test_unavailable_read_is_not_successful_activation(self):
        with patch.object(cli.subprocess, "run", side_effect=FileNotFoundError):
            with patch("builtins.print") as print_mock:
                status = cli.main(["--human-login", "human-operator"])
        self.assertEqual(status, 2)
        result = json.loads(print_mock.call_args.args[0])
        self.assertFalse(result["human_only_break_glass_active"])
        self.assertFalse(result["repository_mutation_authorized"])

    def test_duplicate_json_is_never_accepted_as_evidence(self):
        def duplicate(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, b'{"name":"ok","name":"fake"}', b"")
        with patch.object(cli.subprocess, "run", side_effect=duplicate):
            with self.assertRaises(cli.PreflightReadError):
                cli.read_live_preflight({"human-operator"})


if __name__ == "__main__":
    unittest.main()
