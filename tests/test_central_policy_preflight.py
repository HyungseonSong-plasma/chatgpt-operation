"""#264 central target policy is portable, exact-pinned, and non-executing."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import unittest

from chatgpt_operation.repository.central_policy_preflight import (
    CENTRAL_POLICY_PREFIX,
    CONNECTOR_PROVIDER,
    CentralPolicyBinding,
    require_central_connector_preflight,
)
from chatgpt_operation.repository.mutation import PolicyError
from chatgpt_operation.repository.target_policy_preflight import SAMUEL_REPOSITORY
from test_target_policy_preflight import (
    CONSUMER, HEAD, OTHER, manifest, policy,
)

SOURCE_HEAD = "c" * 40
SOURCE_BLOB = "d" * 40


class FakeGitHubReadTransport:
    def __init__(self, repository):
        self.repository = repository
        self.main_sha = SOURCE_HEAD if repository == SAMUEL_REPOSITORY else HEAD
        self.advance_sha = None
        self.policy = policy()
        self.policy_raw = None
        self.error = None
        self.bad_identity = False
        self.bad_blob = False
        self.bad_size = False
        self.bad_encoding = False
        self.reads = []
        self.writes = []

    def get(self, path, *, query=None):
        self.reads.append((path, query))
        if self.error is not None:
            raise self.error
        if path == "/git/ref/heads/main":
            n = sum(p == path for p, _ in self.reads)
            sha = self.advance_sha if self.advance_sha is not None and n > 1 else self.main_sha
            return {"ref": "refs/heads/main", "object": {"type": "commit", "sha": sha}}
        if path == "/contents/" + CENTRAL_POLICY_PREFIX + "/" + CONSUMER + ".json":
            assert self.repository == SAMUEL_REPOSITORY
            assert query == {"ref": SOURCE_HEAD}
            raw = self.raw()
            blob = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            return {
                "type": "file",
                "path": (path[1:] + ".other") if self.bad_identity else path[1:],
                "encoding": "utf-8" if self.bad_encoding else "base64",
                "content": base64.b64encode(raw).decode(),
                "sha": "e" * 40 if self.bad_blob else blob,
                "size": len(raw) + int(self.bad_size),
            }
        raise AssertionError("unexpected read endpoint " + path)

    def raw(self):
        return self.policy_raw if self.policy_raw is not None else json.dumps(
            self.policy, sort_keys=True, separators=(",", ":")
        ).encode()

    def request(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("preflight must never call GitHub write")


class CentralPolicyTests(unittest.TestCase):
    def setUp(self):
        self.target = FakeGitHubReadTransport(CONSUMER)
        self.source = FakeGitHubReadTransport(SAMUEL_REPOSITORY)

    def binding(self, **changes):
        b = {
            "target_repository": CONSUMER,
            "target_main_sha": HEAD,
            "source_repository": SAMUEL_REPOSITORY,
            "source_main_sha": SOURCE_HEAD,
            "source_blob_sha": hashlib.sha1(
                b"blob " + str(len(self.source.raw())).encode()
                + b"\0" + self.source.raw()
            ).hexdigest(),
        }
        b.update(changes)
        return CentralPolicyBinding(**b)

    def check(self, m=None, binding=None, **changes):
        return require_central_connector_preflight(
            manifest=manifest() if m is None else m,
            target_transport=changes.pop("target_transport", self.target),
            source_transport=changes.pop("source_transport", self.source),
            binding=self.binding() if binding is None else binding,
            expected_target_main_sha=changes.pop("expected_target_main_sha", HEAD),
            provider=changes.pop("provider", CONNECTOR_PROVIDER),
            **changes,
        )

    def test_pinned_source_and_target_accept_bounded_readonly_connector_preflight(self):
        receipt = self.check()
        self.assertEqual(receipt.status, "PREFLIGHT_PASSED_NOT_WRITE_AUTHORIZATION")
        self.assertEqual(receipt.repository, CONSUMER)
        self.assertEqual(receipt.provider, CONNECTOR_PROVIDER)
        self.assertEqual(receipt.source_main_sha, SOURCE_HEAD)
        self.assertEqual(
            receipt.source_policy_path,
            CENTRAL_POLICY_PREFIX + "/" + CONSUMER + ".json",
        )
        self.assertEqual(
            self.source.reads,
            [
                ("/git/ref/heads/main", None),
                ("/contents/" + CENTRAL_POLICY_PREFIX + "/" + CONSUMER + ".json",
                 {"ref": SOURCE_HEAD}),
                ("/git/ref/heads/main", None),
            ],
        )
        self.assertEqual(
            self.target.reads,
            [("/git/ref/heads/main", None), ("/git/ref/heads/main", None)],
        )
        self.assertFalse(self.source.writes)
        self.assertFalse(self.target.writes)

    def test_all_registered_create_update_forms_can_be_checked_without_writes(self):
        for action in ("create", "update", "branch-create"):
            with self.subTest(action=action):
                receipt = self.check(manifest(action=action))
                self.assertEqual(receipt.policy_repository, CONSUMER)
                self.assertFalse(self.source.writes)
                self.assertFalse(self.target.writes)

    def test_missing_binding_and_wrong_provider_fail_without_reads(self):
        # Because None is the default marker in helper, directly call core API.
        with self.assertRaisesRegex(PolicyError, "binding not configured"):
            require_central_connector_preflight(
                manifest=manifest(), target_transport=self.target,
                source_transport=self.source, binding=None,
                expected_target_main_sha=HEAD, provider=CONNECTOR_PROVIDER,
            )
        with self.assertRaisesRegex(PolicyError, "only to registered"):
            self.check(provider="repository-native")
        self.assertFalse(self.source.reads)
        self.assertFalse(self.target.reads)

    def test_samuel_policy_cannot_be_relabelled_as_consumer_policy(self):
        self.source.policy["repository"] = SAMUEL_REPOSITORY
        with self.assertRaisesRegex(PolicyError, "repository binding mismatch"):
            self.check()
        self.assertFalse(self.source.writes)

    def test_source_and_target_transport_identity_must_match(self):
        wrong = FakeGitHubReadTransport("attacker/fork")
        for kwargs in (
            {"target_transport": wrong},
            {"source_transport": wrong},
        ):
            with self.subTest(kwargs=list(kwargs)), self.assertRaisesRegex(
                PolicyError, "transport mismatch"
            ):
                self.check(**kwargs)
        self.assertFalse(wrong.reads)

    def test_wrong_owner_or_target_in_binding_rejected(self):
        for changes in (
            {"source_repository": CONSUMER},
            {"target_repository": "other/repo"},
        ):
            with self.subTest(changes=changes), self.assertRaises(PolicyError):
                self.check(binding=self.binding(**changes))
        with self.assertRaisesRegex(PolicyError, "target identity"):
            self.check(manifest(repository=SAMUEL_REPOSITORY))
        self.assertFalse(self.source.reads)

    def test_stale_invalid_or_changed_target_main_rejected(self):
        for target_sha in (OTHER, "main", "Z" * 40):
            with self.subTest(target_sha=target_sha), self.assertRaises(PolicyError):
                self.check(binding=self.binding(target_main_sha=target_sha))
        with self.assertRaisesRegex(PolicyError, "expected target revision"):
            self.check(expected_target_main_sha=OTHER)
        self.target.advance_sha = OTHER
        with self.assertRaisesRegex(PolicyError, "changed during readback"):
            self.check()
        self.assertFalse(self.source.writes)

    def test_stale_invalid_or_changed_source_main_rejected(self):
        for source_sha in (OTHER, "main", "Z" * 40):
            with self.subTest(source_sha=source_sha), self.assertRaises(PolicyError):
                self.check(binding=self.binding(source_main_sha=source_sha))
        self.source.advance_sha = OTHER
        with self.assertRaisesRegex(PolicyError, "changed during readback"):
            self.check()

    def test_blob_sha_pin_must_match_actual_bytes_and_github_proof(self):
        with self.assertRaisesRegex(PolicyError, "source/blob identity mismatch"):
            self.check(binding=self.binding(source_blob_sha="f" * 40))
        self.source.bad_blob = True
        with self.assertRaisesRegex(PolicyError, "source/blob identity mismatch"):
            self.check()
        self.source.bad_blob = False
        b = self.binding()
        self.source.policy["mutation"]["file_paths"]["allow"] = ["sensitive/**"]
        with self.assertRaisesRegex(PolicyError, "source/blob identity mismatch"):
            self.check(binding=b)
        self.assertFalse(self.source.writes)

    def test_malformed_policy_rejected_and_no_provider_invoked(self):
        for flag in ("bad_identity", "bad_size", "bad_encoding"):
            source = FakeGitHubReadTransport(SAMUEL_REPOSITORY)
            setattr(source, flag, True)
            with self.subTest(flag=flag), self.assertRaises(PolicyError):
                self.check(source_transport=source)
            self.assertFalse(source.writes)
        for raw in (b"{invalid", b'{"schema_version":1,"schema_version":1}',
                    b"\xff", b"", b" " * 65537):
            source = FakeGitHubReadTransport(SAMUEL_REPOSITORY)
            source.policy_raw = raw
            # Pin precisely the malformed raw bytes to test schema/size.
            local_binding = CentralPolicyBinding(
                target_repository=CONSUMER, target_main_sha=HEAD,
                source_repository=SAMUEL_REPOSITORY,
                source_main_sha=SOURCE_HEAD,
                source_blob_sha=hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw
                ).hexdigest(),
            )
            with self.subTest(raw_size=len(raw)), self.assertRaises(PolicyError):
                self.check(source_transport=source, binding=local_binding)
            self.assertFalse(source.writes)

    def test_missing_central_source_fails_closed(self):
        self.source.error = LookupError("404 central policy missing")
        with self.assertRaises(PolicyError):
            self.check()
        self.assertFalse(self.source.writes)

    def test_denied_paths_operations_and_branches_are_not_weakened(self):
        for path in (".github/workflows/secret.yml", "automation/policy.json",
                     "private/access.txt"):
            with self.subTest(path=path), self.assertRaises(PolicyError):
                self.check(manifest(path=path))
        for branch in ("main", "feat/forbidden"):
            with self.subTest(branch=branch), self.assertRaises(PolicyError):
                self.check(manifest(branch=branch))
        self.source.policy["mutation"]["allow"]["file"] = ["create"]
        with self.assertRaisesRegex(PolicyError, "file action denied"):
            self.check()

    def test_changed_target_policy_during_dryrun_cannot_dispatch(self):
        # Positive receipt is not authorization. No dispatch method exists
        # in this module and both transports forbid request().
        result = self.check()
        self.assertEqual(result.status, "PREFLIGHT_PASSED_NOT_WRITE_AUTHORIZATION")
        self.assertEqual(self.target.writes + self.source.writes, [])


if __name__ == "__main__":
    unittest.main()
