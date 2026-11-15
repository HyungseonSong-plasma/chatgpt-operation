"""Trusted central consumer-policy preflight for Samuel connector providers.

This module is a read-only *pre-provider* gate. It does not grant or execute
GitHub writes, select a provider, skip previous blocker history, or activate
cross-repository mutation. A CentralPolicyBinding MUST be issued from trusted
controller configuration after an independent repository-owner review; an
ActionPlan, issue body, tool result or self-authored policy file is not that
configuration.

Repository-native mutation is intentionally unsupported by this resolver:
the native engine still requires its own canonical target policy at runtime.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from chatgpt_operation.repository.mutation import (
    Manifest,
    PolicyError,
    REPOSITORY,
    SHA40,
    authorize_manifest,
    parse_policy,
)
from chatgpt_operation.repository.target_policy_preflight import (
    SAMUEL_REPOSITORY,
    MAX_POLICY_BYTES,
    _json_without_duplicate_keys,
    _observed_main_sha,
)

CENTRAL_POLICY_PREFIX = "automation/consumer-policies"
CONNECTOR_PROVIDER = "github-connector"


@dataclass(frozen=True)
class CentralPolicyBinding:
    """Independent, trusted operator-pinned policy source and target identity.

    This structure is a claimed identity, not authentication itself.
    The caller must obtain it from separately governed trusted configuration,
    never from an ActionPlan or an unverified Issue/PR. Its exact source
    revision and Git blob SHA must be accepted by the target-policy owner.
    """

    target_repository: str
    target_main_sha: str
    source_repository: str
    source_main_sha: str
    source_blob_sha: str


@dataclass(frozen=True)
class CentralPolicyPreflightReceipt:
    """Auditable policy readback; NOT an authorization to write."""

    repository: str
    target_main_sha: str
    provider: str
    source_repository: str
    source_main_sha: str
    source_policy_path: str
    source_blob_sha: str
    policy_repository: str
    status: str = "PREFLIGHT_PASSED_NOT_WRITE_AUTHORIZATION"


def _sha(value: object, what: str) -> str:
    if not isinstance(value, str) or not SHA40.fullmatch(value):
        raise PolicyError(f"central consumer policy {what} must be exact 40-hex SHA")
    return value


def _policy_path(repository: str) -> str:
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise PolicyError("central consumer policy target repository invalid")
    # Path is derived solely from the validated manifest repository.
    # Neither untrusted manifests nor source binding can choose an arbitrary
    # target policy path.
    return CENTRAL_POLICY_PREFIX + "/" + repository + ".json"


def _read_central_policy(
    *,
    source_transport: Any,
    path: str,
    source_main_sha: str,
    source_blob_sha: str,
):
    try:
        result = source_transport.get(
            "/contents/" + path, query={"ref": source_main_sha}
        )
    except Exception as exc:
        raise PolicyError(
            "central consumer policy unavailable: trusted pinned source unreadable"
        ) from exc

    if not (
        isinstance(result, dict)
        and result.get("type") == "file"
        and result.get("path") == path
        and result.get("encoding") == "base64"
        and result.get("sha") == source_blob_sha
        and isinstance(result.get("content"), str)
    ):
        raise PolicyError("central consumer policy source/blob identity mismatch")

    try:
        raw = base64.b64decode(
            result["content"].replace("\n", ""), validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise PolicyError("central consumer policy content encoding invalid") from exc

    if not raw or len(raw) > MAX_POLICY_BYTES or result.get("size") != len(raw):
        raise PolicyError("central consumer policy source byte size mismatch")
    blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    if hashlib.sha1(blob).hexdigest() != source_blob_sha:
        raise PolicyError("central consumer policy raw Git blob SHA mismatch")
    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_json_without_duplicate_keys
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PolicyError("central consumer policy JSON invalid") from exc
    return parse_policy(document)


def require_central_connector_preflight(
    *,
    manifest: Manifest,
    target_transport: Any,
    source_transport: Any,
    binding: CentralPolicyBinding | None,
    expected_target_main_sha: str,
    provider: str,
) -> CentralPolicyPreflightReceipt:
    """Strict read-only central policy gate, prior to a connector provider.

    Preconditions outside this function: trusted capability/skill routing,
    actual target-owner policy approval and pin enrollment, registered work ID,
    blocker-history evaluation, target credential scope and provider selection.
    Passing here is not sufficient to perform a mutation.
    """
    if provider != CONNECTOR_PROVIDER:
        raise PolicyError(
            "central consumer policy applies only to registered github-connector provider"
        )
    if type(binding) is not CentralPolicyBinding:
        raise PolicyError(
            "central consumer policy unavailable: trusted binding not configured"
        )
    target = manifest.repository
    if target == SAMUEL_REPOSITORY or binding.target_repository != target:
        raise PolicyError("central consumer policy target identity mismatch")
    if getattr(target_transport, "repository", None) != target:
        raise PolicyError("central consumer policy target transport mismatch")
    if (
        binding.source_repository != SAMUEL_REPOSITORY
        or getattr(source_transport, "repository", None) != SAMUEL_REPOSITORY
    ):
        raise PolicyError("central consumer policy source transport mismatch")

    source_sha = _sha(binding.source_main_sha, "source revision")
    blob_sha = _sha(binding.source_blob_sha, "source blob")
    target_sha = _sha(binding.target_main_sha, "target revision")
    if target_sha != _sha(expected_target_main_sha, "expected target revision"):
        raise PolicyError("central consumer policy expected target revision mismatch")

    # Only independently observed exact current main revisions may be used.
    # A floating ref or cached policy/target state is never sufficient.
    if _observed_main_sha(target_transport) != target_sha:
        raise PolicyError("central consumer policy target main revision stale")
    if _observed_main_sha(source_transport) != source_sha:
        raise PolicyError("central consumer policy source main revision stale")

    path = _policy_path(target)
    policy = _read_central_policy(
        source_transport=source_transport,
        path=path,
        source_main_sha=source_sha,
        source_blob_sha=blob_sha,
    )
    if policy.repository != target:
        raise PolicyError("central consumer policy repository binding mismatch")
    # Enforce the full operation, path and branch policy, including hardcoded
    # protected Workflow deny. A branch-only ALLOW is not enough.
    authorize_manifest(manifest, policy=policy, repository=target)

    # Detect a ref advance during evidence collection. Subsequent provider
    # writes must still perform their own live exact-SHA preconditions.
    if _observed_main_sha(target_transport) != target_sha:
        raise PolicyError("central consumer policy target main changed during readback")
    if _observed_main_sha(source_transport) != source_sha:
        raise PolicyError("central consumer policy source main changed during readback")

    return CentralPolicyPreflightReceipt(
        repository=target,
        target_main_sha=target_sha,
        provider=provider,
        source_repository=SAMUEL_REPOSITORY,
        source_main_sha=source_sha,
        source_policy_path=path,
        source_blob_sha=blob_sha,
        policy_repository=policy.repository,
    )
