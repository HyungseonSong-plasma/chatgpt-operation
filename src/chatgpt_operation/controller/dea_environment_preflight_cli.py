"""Read-only, administrator-local GitHub configuration preflight for DEA.

Run with the operator's own GitHub CLI authenticated session. No tokens are
requested or printed, and no endpoint other than exact repository GETs is
called. This is NOT a human deployment approval or workflow policy override.

Example:
 python -m chatgpt_operation.controller.dea_environment_preflight_cli \
   --human-login YOUR_GITHUB_USERNAME
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

from chatgpt_operation.controller.dea_environment_preflight import (
    assess_human_environment,
)

REPO = "HyungseonSong-plasma/chatgpt-operation"
ENV = "dea-human-break-glass"
_API_ROOT = f"repos/{REPO}"
_MAX_JSON = 2_000_000
_LOGIN = re.compile(r"[A-Za-z0-9-]{1,39}\Z")


class PreflightReadError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreflightReadError("ambiguous GitHub API object")
        result[key] = value
    return result


def _gh_get(endpoint: str) -> Any:
    """Only a hardcoded small GET endpoint allowlist; never a write action."""
    valid = {
        f"{_API_ROOT}/environments/{ENV}",
        f"{_API_ROOT}/environments/{ENV}/deployment-branch-policies?per_page=100",
        f"{_API_ROOT}/rulesets?per_page=100",
    }
    if endpoint.startswith(f"{_API_ROOT}/rulesets/") and re.fullmatch(
        rf"{re.escape(_API_ROOT)}/rulesets/[1-9][0-9]*", endpoint
    ):
        valid.add(endpoint)
    if endpoint not in valid:
        raise PreflightReadError("endpoint is not in read-only allowlist")
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "GET", endpoint],
            check=False, capture_output=True, timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightReadError("GitHub CLI read unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > _MAX_JSON:
        raise PreflightReadError("GitHub CLI response unavailable or too large")
    try:
        return json.loads(result.stdout.decode("utf-8"),
                          object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, UnicodeError) as exc:
        raise PreflightReadError("invalid read-only GitHub JSON") from exc


def read_live_preflight(expected_humans: set[str]) -> dict[str, Any]:
    if not expected_humans or len(expected_humans) > 6 or any(
        not isinstance(login, str) or not _LOGIN.fullmatch(login)
        for login in expected_humans
    ):
        raise PreflightReadError("provide 1-6 named GitHub user logins")
    environment = _gh_get(f"{_API_ROOT}/environments/{ENV}")
    branch_policies = _gh_get(
        f"{_API_ROOT}/environments/{ENV}/deployment-branch-policies?per_page=100"
    )
    rule_list = _gh_get(f"{_API_ROOT}/rulesets?per_page=100")
    if not isinstance(rule_list, list) or len(rule_list) > 75:
        raise PreflightReadError("incomplete/invalid ruleset list")
    details: list[dict[str, Any]] = []
    for r in rule_list:
        if not isinstance(r, dict) or type(r.get("id")) is not int or r["id"] <= 0:
            raise PreflightReadError("invalid ruleset identity")
        item = _gh_get(f"{_API_ROOT}/rulesets/{r['id']}")
        if not isinstance(item, dict) or item.get("id") != r["id"]:
            raise PreflightReadError("ruleset detail mismatch")
        details.append(item)
    return assess_human_environment(
        environment if isinstance(environment, dict) else None,
        branch_policies if isinstance(branch_policies, dict) else None,
        details, nominated_human_logins=expected_humans,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--human-login", action="append", required=True,
                   help="Human GitHub reviewer login (repeat for more)")
    args = p.parse_args(argv)
    try:
        result = read_live_preflight(set(args.human_login))
    except PreflightReadError:
        result = {
            "status": "HUMAN_CONFIGURATION_READ_UNAVAILABLE",
            "requested_environment": ENV,
            "independent_human_approval": "NOT_VERIFIED",
            "human_only_break_glass_active": False,
            "repository_mutation_authorized": False,
        }
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    # A configuration match is NOT authorization. Admin bypass and actual
    # GitHub deployment-review enforcement need separate manual/live tests.
    return 0 if result["status"] == "CONFIGURATION_SNAPSHOT_MATCH" else 2


if __name__ == "__main__":
    sys.exit(main())
