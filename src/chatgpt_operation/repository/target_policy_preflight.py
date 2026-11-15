"""Repository-bound pre-dispatch mutation policy check.

The default Samuel policy can be used only for Samuel's own repository.
A consumer's policy must be fetched through a trusted transport scoped to
that SAME consumer, at an exact currently observed main commit. No
ActionPlan or Issue may supply a policy location or override the repo identity.

This preflight is necessary, not sufficient, for repository mutation:
the native mutation engine and independent tool/policy/blocker gates remain
authoritative. It never performs a GitHub write.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from chatgpt_operation.repository.branch_preflight import require_allowed_branch
from chatgpt_operation.repository.mutation import (
    Manifest,
    ManifestError,
    PolicyError,
    SHA40,
    authorize_manifest,
    normalize_branch,
    parse_policy,
)

SAMUEL_REPOSITORY = "HyungseonSong-plasma/chatgpt-operation"
POLICY_PATH = "automation/samuel/repository-mutation-policy.json"
CONSUMER_WORKFLOW = "samuel-repository-mutation.yml"
MAX_POLICY_BYTES = 64 * 1024


def _json_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError("duplicate field in consumer repository policy")
        result[key] = value
    return result


def _observed_main_sha(transport: Any) -> str:
    try:
        response = transport.get("/git/ref/heads/main")
    except Exception as exc:
        raise PolicyError("consumer target main HEAD readback unavailable") from exc
    if (
        not isinstance(response, dict)
        or response.get("ref") != "refs/heads/main"
        or not isinstance(response.get("object"), dict)
        or response["object"].get("type") != "commit"
    ):
        raise PolicyError("consumer target main HEAD evidence malformed")
    sha = response["object"].get("sha")
    if not isinstance(sha, str) or not SHA40.fullmatch(sha):
        raise PolicyError("consumer target main HEAD SHA invalid")
    return sha


def _read_pinned_consumer_policy(
    transport: Any, *, expected_main_sha: str
):
    if not isinstance(expected_main_sha, str) or not SHA40.fullmatch(expected_main_sha):
        raise PolicyError("consumer target main revision must be exact 40-hex SHA")
    if _observed_main_sha(transport) != expected_main_sha:
        raise PolicyError("consumer target main revision is stale")

    # Contents API is scoped by transport.repository. Never use a policy
    # supplied by Samuel's checkout or a model-controlled repository path.
    try:
        response = transport.get(
            "/" + "contents/" + POLICY_PATH,
            query={"ref": expected_main_sha},
        )
    except Exception as exc:
        raise PolicyError(
            "consumer repository policy unsupported: trusted target policy unavailable"
        ) from exc

    if (
        not isinstance(response, dict)
        or response.get("type") != "file"
        or response.get("path") != POLICY_PATH
        or response.get("encoding") != "base64"
        or not isinstance(response.get("content"), str)
        or not isinstance(response.get("sha"), str)
    ):
        raise PolicyError("consumer policy pinned GitHub file evidence malformed")
    try:
        content = base64.b64decode(
            response["content"].replace("\n", ""), validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise PolicyError("consumer policy base64 bytes invalid") from exc

    # A Contents API 'sha' is a Git blob identity. Verify against raw bytes,
    # rather than trusting a user-supplied hash or an unpinned file path.
    if len(content) == 0 or len(content) > MAX_POLICY_BYTES:
        raise PolicyError("consumer policy size invalid")
    git_blob = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    if hashlib.sha1(git_blob).hexdigest() != response["sha"]:
        raise PolicyError("consumer policy Git blob SHA mismatch")
    if response.get("size") != len(content):
        raise PolicyError("consumer policy reported byte size mismatch")

    try:
        document = json.loads(
            content.decode("utf-8"), object_pairs_hook=_json_without_duplicate_keys
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PolicyError("consumer policy JSON malformed") from exc

    policy = parse_policy(document)

    # Also fail closed if the policy is moved/modified on main during the
    # two readbacks. A later mutation still needs a separately verified gate.
    if _observed_main_sha(transport) != expected_main_sha:
        raise PolicyError("consumer target main revision changed during preflight")
    return policy


def require_target_mutation_policy(
    *,
    manifest: Manifest,
    transport: Any,
    branch: str,
    expected_main_sha: str,
    dispatch_ref: str,
    workflow: str,
    samuel_local_policy_path: str | Path = POLICY_PATH,
) -> str:
    """Check repository, revision, target policy and manifest before dispatch.

    A caller without a trusted repository-scoped transport fails closed.
    Consumer routing is available only for a consumer-owned runtime whose
    pinned main contains its own independently read-back policy file.
    No consumer policy is provisioned or authorized by this function.
    """
    target = manifest.repository
    runner = getattr(transport, "repository", None)
    if not isinstance(runner, str) or runner != target:
        raise PolicyError(
            "consumer repository policy unsupported: dispatch transport "
            "repository does not match mutation target"
        )

    if target == SAMUEL_REPOSITORY:
        return require_allowed_branch(
            repository=target, branch=branch, policy_path=samuel_local_policy_path
        )

    if dispatch_ref != "main" or workflow != CONSUMER_WORKFLOW:
        raise PolicyError(
            "consumer repository policy unsupported: untrusted dispatch ref/workflow"
        )
    policy = _read_pinned_consumer_policy(
        transport, expected_main_sha=expected_main_sha
    )
    if policy.repository != target:
        raise PolicyError("consumer repository policy binding mismatch")

    try:
        normalized = normalize_branch(branch, "branch")
    except (ManifestError, ValueError) as exc:
        raise PolicyError("consumer target branch invalid") from exc
    authorize_manifest(manifest, policy=policy, repository=target)
    return normalized
