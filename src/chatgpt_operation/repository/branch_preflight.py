"""Fail-closed branch-name preflight for Samuel GitHub create/update routing.

Internal, read-only gate. The repository mutation policy remains authoritative;
this module grants no permission and does not clear historical blockers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from chatgpt_operation.repository.mutation import (
    ManifestError,
    PolicyError,
    _allowed,
    normalize_branch,
    parse_policy,
)


def require_allowed_branch(*, repository: str, branch: str, policy_path: str | Path) -> str:
    """Check an existing/proposed branch against its repo's canonical policy.

    Call before GITHUB_BRANCH_CREATE and GITHUB_PR_CREATE provider execution,
    as well as for connector file writes. The caller must separately check
    trusted work-ID blocker history, exact branch identity, CI, and permissions.
    """
    try:
        document = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PolicyError("branch policy unavailable or invalid") from exc

    policy = parse_policy(document)
    if policy.repository != repository:
        raise PolicyError("branch policy repository binding mismatch")
    try:
        normalized = normalize_branch(branch, "branch")
    except ManifestError as exc:
        raise PolicyError("branch name is invalid") from exc
    if not _allowed(normalized, policy.branch_allow, policy.branch_deny):
        raise PolicyError(f"branch name denied by repository policy: {normalized}")
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Samuel branch-name policy preflight")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--policy", required=True)
    args = parser.parse_args(argv)
    try:
        name = require_allowed_branch(
            repository=args.repository,
            branch=args.branch,
            policy_path=args.policy,
        )
    except PolicyError as exc:
        print(f"DENIED: {exc}", file=sys.stderr)
        return 2
    print(f"ALLOWED: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
