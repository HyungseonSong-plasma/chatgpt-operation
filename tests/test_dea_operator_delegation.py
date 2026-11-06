"""Deterministic negative contracts for one-shot DEA operator delegation.

All grant, signature, revocation and reservation providers here are test
doubles. No test manufactures a live owner authorization.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from chatgpt_operation.controller.dea_operator_delegation import (
    ACTION, DELEGATE_ID, OPERATOR_LOGIN,
    OperatorDelegationError, OperatorDelegationGate, OperatorDelegationGrant,
)
from chatgpt_operation.controller.dea_workflow_authoring_preflight import (
    BRANCH, PATH, REPO, WORK_ID,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def grant():
    return OperatorDelegationGrant(
        grant_id="operator-254-draft-1",
        operator_login=OPERATOR_LOGIN,
        delegate_id=DELEGATE_ID,
        repository=REPO,
        work_id=WORK_ID,
        action=ACTION,
        branch=BRANCH,
        target_path=PATH,
        expected_main_sha=SHA,
        issued_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(hours=1),
        evidence_ref="TEST_ONLY_AUTHENTICATED_OPERATOR_GRANT",
    )


def gate(value=None, *, verified=True, reserved=True, now=NOW):
    read = lambda: grant() if value is None else value
    return OperatorDelegationGate(
        trusted_grant_reader=read,
        trusted_grant_verifier=lambda _: verified,
        atomic_grant_reserver=lambda _: reserved,
        clock=lambda: now,
    )


class OperatorDelegationContractTests(unittest.TestCase):
    def test_valid_scope_and_atomic_one_use_reservation(self):
        used = set()

        def reserve(value):
            if value.grant_id in used:
                return False
            used.add(value.grant_id)
            return True

        checked = OperatorDelegationGate(
            trusted_grant_reader=grant,
            trusted_grant_verifier=lambda _: True,
            atomic_grant_reserver=reserve,
            clock=lambda: NOW,
        )
        self.assertEqual(
            checked.require_and_reserve(expected_main_sha=SHA).grant_id,
            "operator-254-draft-1",
        )
        with self.assertRaisesRegex(
            OperatorDelegationError, "DELEGATION_ALREADY_USED_OR_NOT_RESERVED"
        ):
            checked.require_and_reserve(expected_main_sha=SHA)
        self.assertEqual(used, {"operator-254-draft-1"})

    def test_wrong_identity_target_and_privileged_actions_rejected(self):
        disallowed = {
            "operator_login": "impersonated-owner",
            "delegate_id": "untrusted-bot",
            "repository": "other/repository",
            "work_id": "OTHER-WORK",
            "action": "MERGE_PR",
            "branch": "main",
            "target_path": ".github/workflows/other.yml",
            "expected_main_sha": "b" * 40,
        }
        for field, bad in disallowed.items():
            with self.subTest(field=field), self.assertRaisesRegex(
                OperatorDelegationError, "DELEGATION_SCOPE_MISMATCH"
            ):
                gate(replace(grant(), **{field: bad})).require_and_reserve(
                    expected_main_sha=SHA
                )

    def test_expired_future_dated_or_long_lived_grants_rejected(self):
        disallowed = (
            replace(grant(), expires_at=NOW - timedelta(seconds=1)),
            replace(grant(), issued_at=NOW + timedelta(seconds=1)),
            replace(grant(), expires_at=NOW + timedelta(hours=25)),
            replace(grant(), expires_at=grant().issued_at),
        )
        for value in disallowed:
            with self.subTest(value=value), self.assertRaisesRegex(
                OperatorDelegationError, "DELEGATION_EXPIRED_OR_OUT_OF_BOUNDS"
            ):
                gate(value).require_and_reserve(expected_main_sha=SHA)

    def test_missing_evidence_and_invalid_id_or_time_rejected(self):
        disallowed = (
            (replace(grant(), grant_id="bad"), "DELEGATION_ID_INVALID"),
            (replace(grant(), evidence_ref="  "), "DELEGATION_EVIDENCE_MISSING"),
            (replace(grant(), issued_at=NOW.replace(tzinfo=None)), "DELEGATION_TIME_INVALID"),
            (replace(grant(), expires_at=NOW.replace(tzinfo=None)), "DELEGATION_TIME_INVALID"),
        )
        for value, reason in disallowed:
            with self.subTest(reason=reason), self.assertRaisesRegex(
                OperatorDelegationError, reason
            ):
                gate(value).require_and_reserve(expected_main_sha=SHA)

    def test_wrong_caller_sha_fails_before_read(self):
        reads = []
        checked = OperatorDelegationGate(
            trusted_grant_reader=lambda: reads.append("read") or grant(),
            trusted_grant_verifier=lambda _: True,
            atomic_grant_reserver=lambda _: True,
            clock=lambda: NOW,
        )
        with self.assertRaisesRegex(
            OperatorDelegationError, "EXPECTED_MAIN_SHA_INVALID"
        ):
            checked.require_and_reserve(expected_main_sha="main")
        self.assertEqual(reads, [])

    def test_untyped_grant_is_rejected(self):
        with self.assertRaisesRegex(
            OperatorDelegationError, "TYPED_DELEGATION_REQUIRED"
        ):
            gate({"approved": True}).require_and_reserve(expected_main_sha=SHA)

    def test_verifier_must_return_exact_true_not_truthy(self):
        for value in (False, 1, "yes", None):
            with self.subTest(value=value), self.assertRaisesRegex(
                OperatorDelegationError, "DELEGATION_NOT_AUTHENTIC_OR_REVOKED"
            ):
                gate(verified=value).require_and_reserve(expected_main_sha=SHA)

    def test_reserver_must_return_exact_true_not_truthy(self):
        for value in (False, 1, "yes", None):
            with self.subTest(value=value), self.assertRaisesRegex(
                OperatorDelegationError, "DELEGATION_ALREADY_USED_OR_NOT_RESERVED"
            ):
                gate(reserved=value).require_and_reserve(expected_main_sha=SHA)

    def test_missing_or_throwing_trusted_host_provider_is_not_authority(self):
        with self.assertRaisesRegex(
            OperatorDelegationError, "TRUSTED_DELEGATION_BOUNDARY_REQUIRED"
        ):
            OperatorDelegationGate(
                trusted_grant_reader=None,
                trusted_grant_verifier=lambda _: True,
                atomic_grant_reserver=lambda _: True,
            )
        scenarios = (
            ("trusted_grant_reader", "DELEGATION_READ_UNAVAILABLE"),
            ("trusted_grant_verifier", "DELEGATION_VERIFIER_UNAVAILABLE"),
            ("atomic_grant_reserver", "DELEGATION_RESERVATION_UNAVAILABLE"),
        )
        for broken, reason in scenarios:
            callbacks = {
                "trusted_grant_reader": grant,
                "trusted_grant_verifier": lambda _: True,
                "atomic_grant_reserver": lambda _: True,
                "clock": lambda: NOW,
            }

            def fail(*args):
                raise RuntimeError("provider unavailable")

            callbacks[broken] = fail
            with self.subTest(provider=broken), self.assertRaisesRegex(
                OperatorDelegationError, reason
            ):
                OperatorDelegationGate(**callbacks).require_and_reserve(
                    expected_main_sha=SHA
                )


if __name__ == "__main__":
    unittest.main()
