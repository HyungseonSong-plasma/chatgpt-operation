"""Subprocess crash/restart integration for the actual SamuelController.run_cycle.

Runs real production CLI code on an isolated GitHub-Issue-shaped ledger,
kills the worker OS process during unit 31, then starts a fresh process.
No live controller, GitHub issue, or repository mutation is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from chatgpt_operation.controller.durable_state import (
    encode_state, load_state_comment,
)
from chatgpt_operation.controller.progress_resume import (
    attach_checkpoint, create_checkpoint, detail_digest,
    evaluate_resume, refresh_unit_inputs,
)
from chatgpt_operation.controller.research import ResearchState


SOURCE = Path("src/chatgpt_operation/controller")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_inputs() -> dict[str, str]:
    files = sorted(SOURCE.glob("*.py"))[:40]
    if len(files) != 40:
        raise AssertionError("integration needs 40 actual tracked source units")
    return {p.as_posix(): sha(p.read_bytes()) for p in files}


def prepare(directory: Path) -> dict:
    live = expected_inputs()
    units = [
        {
            "id": path,
            "input_sha256": digest,
            "requires": [],
            "gates": ["SOURCE_VERIFIED"],
        }
        for path, digest in live.items()
    ]
    plan = sha(json.dumps(units, sort_keys=True).encode("utf-8"))
    policy = sha(b"samuel-controller-isolated-readonly-crash-restart-v1")
    checkpoint = create_checkpoint(
        work_id="crash-restart-ci-pilot",
        plan_sha256=plan,
        policy_sha256=policy,
        units=units,
    )
    state = attach_checkpoint(
        ResearchState("crash-restart-ci-pilot", "actual source snapshot read-only scan"),
        checkpoint,
    )
    (directory / "comments.json").write_text(
        json.dumps([{"id": 44, "body": encode_state(state)}]),
        encoding="utf-8",
    )
    context = {
        "plan_sha256": plan,
        "policy_sha256": policy,
        "live_inputs": live,
        "gate_states": {"SOURCE_VERIFIED": "PASS"},
    }
    (directory / "context.json").write_text(
        json.dumps(context), encoding="utf-8",
    )
    return context


WORKER = r'''
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time

from chatgpt_operation.cli import main as cli_main
from chatgpt_operation.controller.durable_state import (
    load_state_comment, state_write_request,
    validate_state_write_precondition,
)
from chatgpt_operation.controller.progress_resume import record_verified_unit

root = Path(sys.argv[1])
mode = sys.argv[2]
completed_in_this_process = []
while True:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = cli_main([
            "controller", "run-cycle",
            "--comments", str(root / "comments.json"),
            "--progress-context", str(root / "context.json"),
            "--event-name", "workflow_dispatch",
            "--decisions", "automation/samuel/decisions.json",
            "--result", str(root / "cycle.json"),
        ])
    if result != 0:
        raise RuntimeError("real Controller.run-cycle failed: " + stdout.getvalue())
    cycle = json.loads((root / "cycle.json").read_text(encoding="utf-8"))
    selected = cycle["selected_work"]
    if selected["kind"] != "progress_resume":
        raise AssertionError("did not execute actual Controller progress path")
    if cycle["execution_command"] is not None or cycle["state_write"] is not None:
        raise AssertionError("read-only Controller unexpectedly issued a mutation")
    if selected["status"] == "COMPLETE":
        break
    if selected["status"] != "READY":
        raise AssertionError("unexpected progress decision: " + str(selected))
    number = selected["ready"][0]
    if mode == "before-crash" and number == 30:
        # This worker has begun the 31st unit but not produced a verified
        # ledger write. Its parent SIGKILLs the entire Python process.
        (root / "interruption-marker.txt").write_text(
            "active unit=30; saved=0..29", encoding="utf-8",
        )
        while True:
            time.sleep(0.1)
    context = json.loads((root / "context.json").read_text(encoding="utf-8"))
    comments = json.loads((root / "comments.json").read_text(encoding="utf-8"))
    state = load_state_comment(comments)
    unit = state.progress_checkpoint["units"][number]
    path = Path(unit["id"])
    content = path.read_text(encoding="utf-8")
    detail = {
        "path": unit["id"],
        "content_sha256": context["live_inputs"][unit["id"]],
        "line_count": len(content.splitlines()),
        "analysis": {
            "imports": [line for line in content.splitlines()
                        if line.startswith("from ") or line.startswith("import ")],
            "headings": [line for line in content.splitlines()
                         if line.startswith("# ")],
        },
    }
    updated = record_verified_unit(
        state,
        unit_id=unit["id"],
        input_sha256=context["live_inputs"][unit["id"]],
        outcome="PASS",
        detail=detail,
        gate_states=context["gate_states"],
    )
    request = state_write_request(comments, updated)
    validate_state_write_precondition(comments, request)
    if request["method"] != "PATCH" or request["comment_id"] != 44:
        raise AssertionError("unexpected state persistence strategy")
    next_comments = [{"id": 44, "body": request["body"]}]
    temporary = root / "comments-new.json"
    temporary.write_text(json.dumps(next_comments), encoding="utf-8")
    os.replace(temporary, root / "comments.json")
    completed_in_this_process.append(number)
(root / ("completed-" + mode + ".json")).write_text(
    json.dumps(completed_in_this_process), encoding="utf-8",
)
'''


class ControllerCrashRestartIntegrationTests(unittest.TestCase):
    def test_actual_run_cycle_after_sigkill_resumes_from_30_of_40(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            context = prepare(folder)
            first = subprocess.Popen(
                [sys.executable, "-c", WORKER, str(folder), "before-crash"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 24
                while not (folder / "interruption-marker.txt").exists():
                    if first.poll() is not None:
                        out, err = first.communicate(timeout=2)
                        self.fail(
                            "worker stopped before interruption point: "
                            + err.decode(errors="replace")
                            + out.decode(errors="replace")
                        )
                    if time.monotonic() > deadline:
                        self.fail("first worker did not reach unit 31")
                    time.sleep(0.03)
            finally:
                if first.poll() is None:
                    first.kill()  # Actual OS process termination.
                first.communicate(timeout=6)
            self.assertNotEqual(first.returncode, 0)

            comments = json.loads(
                (folder / "comments.json").read_text(encoding="utf-8")
            )
            before = load_state_comment(comments)
            receipts_before = before.progress_checkpoint["receipts"]
            self.assertEqual(sorted(int(n) for n in receipts_before), list(range(30)))
            self.assertNotIn("30", receipts_before)
            self.assertEqual(
                evaluate_resume(
                    before,
                    plan_sha256=context["plan_sha256"],
                    policy_sha256=context["policy_sha256"],
                    live_inputs=context["live_inputs"],
                    gate_states=context["gate_states"],
                )["ready"], list(range(30, 40)),
            )

            # A *new* Python interpreter with no shared memory restores
            # ResearchState through actual run-cycle and commits 10 units.
            restarted = subprocess.run(
                [sys.executable, "-c", WORKER, str(folder), "after-restart"],
                capture_output=True, text=True, timeout=25,
            )
            self.assertEqual(
                restarted.returncode, 0,
                restarted.stderr + restarted.stdout,
            )
            observed = json.loads(
                (folder / "completed-after-restart.json").read_text(encoding="utf-8")
            )
            self.assertEqual(observed, list(range(30, 40)))
            after = load_state_comment(json.loads(
                (folder / "comments.json").read_text(encoding="utf-8")
            ))
            receipts_after = after.progress_checkpoint["receipts"]
            self.assertEqual(len(receipts_after), 40)
            for key, receipt in receipts_before.items():
                self.assertEqual(receipts_after[key], receipt)
                self.assertEqual(
                    receipt["detail_sha256"], detail_digest(receipt["detail"])
                )
            self.assertEqual(after.revision - before.revision, 10)

            # A second replay is a no-op, not a repeat analysis.
            another = subprocess.run(
                [sys.executable, "-c", WORKER, str(folder), "already-complete"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(another.returncode, 0, another.stderr)
            self.assertEqual(json.loads(
                (folder / "completed-already-complete.json").read_text(encoding="utf-8")
            ), [])

            # A source change at one completed unit requires a scoped
            # refresh but does not erase independent verified receipts.
            inputs = dict(context["live_inputs"])
            changed_path = list(inputs)[17]
            inputs[changed_path] = sha(b"changed byte-for-byte source identity")
            self.assertEqual(evaluate_resume(
                after, plan_sha256=context["plan_sha256"],
                policy_sha256=context["policy_sha256"],
                live_inputs=inputs, gate_states=context["gate_states"],
            )["status"], "REFRESH_REQUIRED")
            refreshed = refresh_unit_inputs(after, live_inputs=inputs)
            self.assertEqual(len(refreshed.progress_checkpoint["receipts"]), 39)
            self.assertNotIn("17", refreshed.progress_checkpoint["receipts"])
            self.assertEqual(
                evaluate_resume(
                    refreshed, plan_sha256=context["plan_sha256"],
                    policy_sha256=context["policy_sha256"],
                    live_inputs=inputs, gate_states=context["gate_states"],
                )["ready"], [17],
            )
            print(
                "CONTROLLER_CRASH_RESTART=PASS actual_sigkill=1 "
                "saved_before=30 resumed=10 duplicate=0 "
                "valid_receipts=40 scoped_refresh=1",
                flush=True,
            )


if __name__ == "__main__":
    unittest.main()
