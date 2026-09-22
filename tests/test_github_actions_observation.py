import unittest

from chatgpt_operation.github.actions_observation import evaluate


class ActionsObservationTests(unittest.TestCase):
    def snapshot(self, *, observed="2026-09-21T10:00:20Z", complete=True, runs=None, **request):
        base = {
            "workflow": "experiment.yml",
            "event": "workflow_dispatch",
            "correlation_id": "exp-26",
            "head_sha": "abc123",
            "ref": "refs/heads/main",
            "requested_at": "2026-09-21T10:00:00Z",
            "visibility_grace_seconds": 60,
        }
        base.update(request)
        return {"request": base, "observation": {"observed_at": observed, "enumeration_complete": complete, "runs": runs or []}}

    def candidate_run(self, **overrides):
        base = {
            "run_id": 100,
            "workflow": "experiment.yml",
            "event": "workflow_dispatch",
            "correlation_id": "exp-26",
            "head_sha": "abc123",
            "ref": "refs/heads/main",
            "created_at": "2026-09-21T10:00:05Z",
            "run_attempt": 1,
            "status": "in_progress",
            "conclusion": None,
        }
        base.update(overrides)
        return base

    def test_active_and_terminal_match(self):
        self.assertEqual(evaluate(self.snapshot(runs=[self.candidate_run()]))["status"], "MATCHED_ACTIVE")
        self.assertEqual(evaluate(self.snapshot(runs=[self.candidate_run(status="completed", conclusion="success")]))["status"], "MATCHED_TERMINAL")

    def test_immediate_zero_is_pending_but_grace_expired_is_no_match(self):
        self.assertEqual(evaluate(self.snapshot())["status"], "PENDING_VISIBILITY")
        self.assertEqual(evaluate(self.snapshot(observed="2026-09-21T10:02:00Z"))["status"], "NO_MATCH")

    def test_incomplete_enumeration_fails_closed(self):
        self.assertEqual(evaluate(self.snapshot(complete=False))["status"], "OBSERVATION_INCOMPLETE")

    def test_wrong_identity_constraints_do_not_match(self):
        for change in (
            {"workflow": "other.yml"}, {"event": "push"}, {"correlation_id": "other"},
            {"head_sha": "def456"}, {"ref": "refs/heads/other"}
        ):
            self.assertEqual(evaluate(self.snapshot(observed="2026-09-21T10:02:00Z", runs=[self.candidate_run(**change)]))["status"], "NO_MATCH")

    def test_stale_only(self):
        stale = self.candidate_run(created_at="2026-09-21T09:59:59Z")
        self.assertEqual(evaluate(self.snapshot(runs=[stale]))["status"], "STALE_ONLY")

    def test_duplicate_candidates_are_ambiguous(self):
        runs = [self.candidate_run(run_id=100), self.candidate_run(run_id=101, created_at="2026-09-21T10:00:06Z")]
        self.assertEqual(evaluate(self.snapshot(runs=runs))["status"], "AMBIGUOUS_MATCH")

    def test_run_attempt_distinguishes_rerun(self):
        runs = [self.candidate_run(run_id=100, run_attempt=1), self.candidate_run(run_id=100, run_attempt=2)]
        result = evaluate(self.snapshot(runs=runs, run_attempt=2))
        self.assertEqual(result["status"], "MATCHED_ACTIVE")
        self.assertEqual(result["matched_run_ids"], [100])

    def test_missing_requested_evidence_fails_closed(self):
        candidate = self.candidate_run(correlation_id=None)
        self.assertEqual(evaluate(self.snapshot(runs=[candidate]))["status"], "OBSERVATION_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
