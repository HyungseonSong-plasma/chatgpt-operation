"""Recovery qualification for evidence-preserving read-only progress.

No GitHub writes are performed by these tests. Race-free persistence still
requires one serialized authoritative writer; comment PATCH is not CAS.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from chatgpt_operation.controller.durable_state import (
    decode_state, encode_state, state_write_request,
    validate_state_write_precondition,
)
from chatgpt_operation.cli import main as cli_main
from chatgpt_operation.controller.progress_resume import (
    ProgressResumeError,
    attach_checkpoint,
    create_checkpoint,
    detail_digest,
    evaluate_resume,
    reconcile_progress_conflict,
    record_verified_unit,
    refresh_unit_inputs,
    validate_checkpoint,
)
from chatgpt_operation.controller.research import ResearchState


def sha(character: str) -> str:
    return character * 64


def units():
    return [
        {"id": "scan/a.md", "input_sha256": sha("a"), "requires": [], "gates": ["snapshot"]},
        {"id": "scan/b.md", "input_sha256": sha("b"), "requires": [], "gates": []},
        {"id": "check/inbound", "input_sha256": sha("c"), "requires": [0], "gates": []},
    ]


def setup():
    state = ResearchState("codeqa-issue-288", "exact-tree read-only audit", revision=4)
    checkpoint = create_checkpoint(
        work_id=state.research_id,
        plan_sha256=sha("d"),
        policy_sha256=sha("e"),
        units=units(),
    )
    return attach_checkpoint(state, checkpoint)


def live(state=None):
    cp = setup().progress_checkpoint if state is None else state.progress_checkpoint
    return {u["id"]: u["input_sha256"] for u in cp["units"]}


def finish(state, unit_id, detail, *, input_sha256=None):
    unit = next(u for u in state.progress_checkpoint["units"] if u["id"] == unit_id)
    return record_verified_unit(
        state,
        unit_id=unit_id,
        input_sha256=input_sha256 or unit["input_sha256"],
        outcome="PASS",
        detail=detail,
        gate_states={"snapshot": "PASS"},
    )


def resume(state, *, inputs=None, policy=None, plan=None, gates=None):
    return evaluate_resume(
        state,
        plan_sha256=plan or sha("d"),
        policy_sha256=policy or sha("e"),
        live_inputs=live(state) if inputs is None else inputs,
        gate_states={"snapshot": "PASS"} if gates is None else gates,
    )


class ProgressResumeTests(unittest.TestCase):
    def test_resume_from_last_verified_unit_and_replay_is_noop(self):
        start = setup()
        self.assertEqual(resume(start)["ready"], [0, 1])
        detail = {
            "counts": {"inbound": 3, "outbound": 7},
            "findings": [{"file": "docs/a.md", "line": 34, "text": "한글 경로"}],
        }
        advanced = finish(start, "scan/a.md", detail)
        self.assertEqual(advanced.revision, start.revision + 1)
        restored = decode_state(encode_state(advanced))
        self.assertEqual(restored.progress_checkpoint["receipts"]["0"]["detail"], detail)
        self.assertEqual(resume(restored)["completed"], [0])
        self.assertEqual(resume(restored)["ready"], [1, 2])
        replayed = finish(restored, "scan/a.md", detail)
        self.assertEqual(replayed.revision, restored.revision)
        with self.assertRaisesRegex(ProgressResumeError, "conflicting replay"):
            finish(restored, "scan/a.md", {"counts": {"inbound": 999}})

    def test_large_details_are_lossless_in_existing_zlib_ledger(self):
        detail = {"complete_raw_evidence": "검증" * 20000}
        completed = finish(setup(), "scan/a.md", detail)
        body = encode_state(completed)
        self.assertIn('"encoding":"zlib+base64"', body)
        decoded = decode_state(body)
        self.assertEqual(decoded.progress_checkpoint["receipts"]["0"]["detail"], detail)
        self.assertEqual(
            decoded.progress_checkpoint["receipts"]["0"]["detail_sha256"],
            detail_digest(detail),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            decoded.save(path)
            self.assertEqual(
                ResearchState.load(path).progress_checkpoint,
                decoded.progress_checkpoint,
            )

    def test_progress_bumps_durable_envelope_version_only_when_present(self):
        legacy = ResearchState("legacy-work", "existing state", revision=2)
        self.assertIn('"schema_version":4', encode_state(legacy))
        self.assertIsNone(decode_state(encode_state(legacy)).progress_checkpoint)

        checkpointed = setup()
        body = encode_state(checkpointed)
        self.assertIn('"schema_version":5', body)
        self.assertIsNotNone(decode_state(body).progress_checkpoint)
        # An old decoder will reject v5 instead of silently dropping progress.
        downgraded = body.replace('"schema_version":5', '"schema_version":4', 1)
        with self.assertRaisesRegex(ValueError, "requires state schema v5"):
            decode_state(downgraded)

    def test_missing_or_failed_gate_blocks_completion(self):
        state = setup()
        self.assertEqual(resume(state, gates={})["ready"], [1])
        self.assertEqual(resume(state, gates={})["waiting_gates"], [0])
        with self.assertRaisesRegex(ProgressResumeError, "required gate"):
            record_verified_unit(
                state, unit_id="scan/a.md", input_sha256=sha("a"),
                outcome="PASS", detail={}, gate_states={},
            )
        with self.assertRaisesRegex(ProgressResumeError, "prerequisite"):
            finish(state, "check/inbound", {"pass": True})

    def test_only_changed_inputs_and_transitive_dependents_are_invalidated(self):
        state = finish(setup(), "scan/a.md", {"a": 1})
        state = finish(state, "scan/b.md", {"b": 2})
        state = finish(state, "check/inbound", {"c": 3})
        self.assertEqual(resume(state)["status"], "COMPLETE")

        inputs = live(state)
        inputs["scan/a.md"] = sha("f")
        result = resume(state, inputs=inputs)
        self.assertEqual(result["status"], "REFRESH_REQUIRED")
        self.assertEqual(result["stale"], [0])
        refreshed = refresh_unit_inputs(state, live_inputs=inputs)
        self.assertEqual(sorted(refreshed.progress_checkpoint["receipts"]), ["1"])
        self.assertEqual(resume(refreshed)["ready"], [0])
        self.assertEqual(resume(refreshed)["completed"], [1])
        self.assertEqual(refreshed.revision, state.revision + 1)

    def test_plan_or_policy_change_blocks_without_silently_reusing_evidence(self):
        state = finish(setup(), "scan/a.md", {"a": 1})
        self.assertEqual(resume(state, policy=sha("f"))["status"], "POLICY_CHANGED")
        self.assertEqual(resume(state, plan=sha("f"))["status"], "PLAN_CHANGED")
        with self.assertRaisesRegex(ProgressResumeError, "incomplete"):
            evaluate_resume(
                state, plan_sha256=sha("d"), policy_sha256=sha("e"),
                live_inputs={"scan/a.md": sha("a")}, gate_states={},
            )

    def test_tampering_and_missing_dependency_are_rejected_on_restore(self):
        s = finish(setup(), "scan/a.md", {"matches": [1, 2]})
        corrupt = copy.deepcopy(s)
        corrupt.progress_checkpoint["receipts"]["0"]["detail"]["matches"][0] = 999
        with self.assertRaisesRegex(ProgressResumeError, "digest mismatch"):
            decode_state(encode_state(corrupt))
        corrupt = copy.deepcopy(s)
        corrupt.progress_checkpoint["receipts"]["2"] = {
            "input_sha256": sha("c"),
            "outcome": "PASS",
            "detail_sha256": detail_digest({"ok": True}),
            "detail": {"ok": True},
        }
        corrupt.progress_checkpoint["receipts"].pop("0")
        with self.assertRaisesRegex(ProgressResumeError, "missing dependency"):
            validate_checkpoint(corrupt.progress_checkpoint)

    def test_disjoint_verified_progress_can_be_proposed_not_written(self):
        base = setup()
        current = finish(base, "scan/a.md", {"a": "original"})
        proposed = finish(base, "scan/b.md", {"b": "independent"})
        decision, candidate = reconcile_progress_conflict(base, current, proposed)
        self.assertEqual(decision, "MERGE_DISJOINT_PROPOSAL")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.revision, current.revision + 1)
        self.assertEqual(sorted(candidate.progress_checkpoint["receipts"]), ["0", "1"])
        self.assertEqual(
            reconcile_progress_conflict(base, candidate, proposed),
            ("ALREADY_APPLIED", None),
        )
        self.assertEqual(
            reconcile_progress_conflict(base, current, base),
            ("BLOCK_REVISION", None),
        )

    def test_conflicting_progress_or_executing_state_is_not_merged(self):
        base = setup()
        current = finish(base, "scan/a.md", {"a": 1})
        proposed = finish(base, "scan/a.md", {"a": 2})
        self.assertEqual(
            reconcile_progress_conflict(base, current, proposed)[0],
            "BLOCK_CONFLICTING_RECEIPT",
        )
        changed_action = copy.deepcopy(current)
        changed_action.action_queue["other"] = {"status": "dispatch_intent"}
        self.assertEqual(
            reconcile_progress_conflict(base, changed_action, proposed)[0],
            "BLOCK_OTHER_STATE_CHANGED",
        )
        changed_policy = copy.deepcopy(current)
        changed_policy.progress_checkpoint["policy_sha256"] = sha("f")
        self.assertEqual(
            reconcile_progress_conflict(base, changed_policy, proposed)[0],
            "BLOCK_SCOPE_CHANGED",
        )

    def test_existing_issue_ledger_can_be_consumed_by_read_only_cli(self):
        state = finish(setup(), "scan/a.md", {"inbound_links": 3})
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            comments_file = folder / "comments.json"
            input_file = folder / "input.json"
            output_file = folder / "out.json"
            comments_file.write_text(
                json.dumps([{"id": 44, "body": encode_state(state)}]),
                encoding="utf-8",
            )
            input_file.write_text(
                json.dumps({
                    "plan_sha256": sha("d"),
                    "policy_sha256": sha("e"),
                    "live_inputs": live(state),
                    "gate_states": {"snapshot": "PASS"},
                }),
                encoding="utf-8",
            )
            exit_code = cli_main([
                "controller", "resume-progress",
                "--comments", str(comments_file),
                "--input", str(input_file),
                "--result", str(output_file),
            ])
            self.assertEqual(exit_code, 0)
            output = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(output["status"], "READY")
            self.assertEqual(output["completed"], [0])
            self.assertEqual(output["ready"], [1, 2])

    def test_conflict_requires_authoritative_read_then_explicit_rebase(self):
        base = setup()
        current = finish(base, "scan/a.md", {"a": 1})
        proposed = finish(base, "scan/b.md", {"b": 2})
        base_comments = [{"id": 44, "body": encode_state(base)}]
        current_comments = [{"id": 44, "body": encode_state(current)}]
        stale_request = state_write_request(base_comments, proposed)
        with self.assertRaisesRegex(ValueError, "stale durable state precondition"):
            validate_state_write_precondition(current_comments, stale_request)
        disposition, rebased = reconcile_progress_conflict(base, current, proposed)
        self.assertEqual(disposition, "MERGE_DISJOINT_PROPOSAL")
        fresh_request = state_write_request(current_comments, rebased)
        validate_state_write_precondition(current_comments, fresh_request)
        self.assertEqual(fresh_request["expected_previous_revision"], current.revision)
        self.assertEqual(fresh_request["expected_revision"], current.revision + 1)

    def test_refresh_refuses_foreign_checkpoint_identity(self):
        state = setup()
        state.research_id = "unrelated-research"
        with self.assertRaisesRegex(ProgressResumeError, "identity changed"):
            refresh_unit_inputs(state, live_inputs=live(state))

    def test_invalid_progress_cannot_overwrite_existing_state(self):
        state = setup()
        with self.assertRaisesRegex(ProgressResumeError, "cannot be overwritten"):
            attach_checkpoint(state, create_checkpoint(
                work_id=state.research_id,
                plan_sha256=sha("d"),
                policy_sha256=sha("e"),
                units=units(),
            ))
        with self.assertRaisesRegex(ProgressResumeError, "different research"):
            attach_checkpoint(
                ResearchState("another", "no"),
                create_checkpoint(
                    work_id="codeqa-issue-288",
                    plan_sha256=sha("d"),
                    policy_sha256=sha("e"),
                    units=units(),
                ),
            )


if __name__ == "__main__":
    unittest.main()
