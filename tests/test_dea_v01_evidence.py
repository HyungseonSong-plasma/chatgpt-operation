"""Adversarial tests for DEA vector fitness and finite-scope semantics."""
from __future__ import annotations

import copy
import unittest

from chatgpt_operation.controller.dea_v01_fitness import evaluate, FitnessContractError
from chatgpt_operation.controller.dea_v01_semantics import (
    compare_observations, SemanticContractError,
)

A, B, C, D, E, F, G, H = [c * 40 for c in "abcdef12"]
PROFILE = {
    "analyzer_sha": B, "profile_sha": C, "oracle_sha": D,
    "measurement_set_sha": E,
    "hard_gates": ["ci", "semantic_contract", "policy"],
    "metrics": {"complexity": "min", "performance": "max"},
}


def receipt(sha, **kwargs):
    return {
        "observed_head_sha": sha,
        "analyzer_sha": B, "profile_sha": C, "oracle_sha": D,
        "measurement_set_sha": E, "evidence_ref": "fixture:pinned",
        **kwargs,
    }


def candidate(name, head, complexity, performance, gates=None):
    gates = gates or {x: "PASS" for x in PROFILE["hard_gates"]}
    return {
        "id": name, "head_sha": head, "base_sha": A,
        "generation": 0 if name == "baseline" else 1,
        "evidence": {
            "hard_gates": {k: receipt(head, status=v) for k, v in gates.items()},
            "metrics": {
                "complexity": receipt(head, value=complexity),
                "performance": receipt(head, value=performance),
            },
        },
    }


def manifest():
    return {
        "schema_version": 1, "work_id": "issue:246:v0.2-fixture",
        "base_sha": A, "profile": PROFILE, "baseline_id": "baseline",
        "candidates": [
            candidate("baseline", A, 10, 50),
            candidate("safe", F, 8, 60),
            candidate("fast", G, 9, 80),
            candidate("weak", H, 12, 45),
        ],
    }


def snapshot(sha):
    return {
        "source_sha": sha, "oracle_sha": D, "input_set_sha": E,
        "environment_sha": B,
        "captured_dimensions": ["return_value", "exceptions", "side_effects"],
        "cases": [
            {"case_id": "normal", "input_sha": C,
             "status": "OBSERVED", "observation_sha": F},
            {"case_id": "error", "input_sha": D,
             "status": "OBSERVED", "observation_sha": G},
        ],
    }


class FitnessTests(unittest.TestCase):
    def test_pareto_tradeoffs_and_no_promotion(self):
        r = evaluate(manifest())
        self.assertEqual(r["pareto_review_set"], ["fast", "safe"])
        self.assertTrue(r["baseline_preserved"])
        self.assertIsNone(r["champion"])
        self.assertFalse(r["repository_mutation_authorized"])
        self.assertEqual(r["evidence_authentication"], "NOT_ATTESTED_BY_THIS_MODULE")

    def test_failed_semantics_excludes_best_metric(self):
        m = manifest()
        m["candidates"][1] = candidate("safe", F, 0, 999, {
            "ci": "PASS", "semantic_contract": "FAIL", "policy": "PASS"})
        r = evaluate(m)
        self.assertEqual(r["candidate_evaluations"]["safe"]["state"], "INFEASIBLE")
        self.assertNotIn("safe", r["pareto_review_set"])

    def test_unknown_semantics_not_pass(self):
        m = manifest()
        m["candidates"][1]["evidence"]["hard_gates"]["semantic_contract"]["status"] = "UNKNOWN"
        self.assertEqual(evaluate(m)["candidate_evaluations"]["safe"]["state"],
                         "UNKNOWN_HARD_GATE")

    def test_unknown_metric_not_compared(self):
        m = manifest()
        m["candidates"][1]["evidence"]["metrics"]["performance"]["value"] = None
        self.assertEqual(evaluate(m)["candidate_evaluations"]["safe"]["state"],
                         "UNKNOWN_METRICS")

    def test_missing_baseline_evidence_blocks_review_set(self):
        m = manifest()
        m["candidates"][0]["evidence"]["hard_gates"]["ci"]["status"] = "UNKNOWN"
        r = evaluate(m)
        self.assertEqual(r["decision"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["pareto_review_set"], [])

    def test_stale_heads_and_oracles_rejected(self):
        m = manifest()
        m["candidates"][1]["evidence"]["hard_gates"]["ci"]["observed_head_sha"] = H
        with self.assertRaises(FitnessContractError):
            evaluate(m)
        m = manifest()
        m["candidates"][1]["evidence"]["metrics"]["complexity"]["oracle_sha"] = G
        with self.assertRaises(FitnessContractError):
            evaluate(m)

    def test_nonfinite_boolean_and_duplicate_candidates_rejected(self):
        for value in (float("nan"), float("inf"), True):
            m = manifest()
            m["candidates"][1]["evidence"]["metrics"]["complexity"]["value"] = value
            with self.subTest(value=value), self.assertRaises(FitnessContractError):
                evaluate(m)
        m = manifest()
        m["candidates"][1]["id"] = "baseline"
        with self.assertRaises(FitnessContractError):
            evaluate(m)

    def test_baseline_cannot_be_mutated(self):
        m = manifest()
        m["candidates"][0]["head_sha"] = F
        with self.assertRaises(FitnessContractError):
            evaluate(m)

    def test_replay_is_deterministic(self):
        self.assertEqual(evaluate(manifest()), evaluate(copy.deepcopy(manifest())))


class SemanticTests(unittest.TestCase):
    def test_matching_cases_only_establish_bounded_compatibility(self):
        r = compare_observations(snapshot(A), snapshot(F),
                                 base_sha=A, candidate_sha=F)
        self.assertEqual(r["status"], "PASS_BOUNDED")
        self.assertEqual(r["external_consumers"], "NOT_EVALUATED")
        self.assertEqual(r["universal_semantic_equivalence"], "NOT_PROVEN")

    def test_changed_behavior_fails(self):
        c = snapshot(F)
        c["cases"][0]["observation_sha"] = H
        self.assertEqual(compare_observations(snapshot(A), c,
                         base_sha=A, candidate_sha=F)["status"], "FAIL")

    def test_missing_behavior_unknown(self):
        c = snapshot(F)
        c["cases"].pop()
        self.assertEqual(compare_observations(snapshot(A), c,
                         base_sha=A, candidate_sha=F)["status"], "UNKNOWN")

    def test_unobserved_behavior_unknown(self):
        c = snapshot(F)
        c["cases"][0].update(status="UNKNOWN", observation_sha=None)
        self.assertEqual(compare_observations(snapshot(A), c,
                         base_sha=A, candidate_sha=F)["status"], "UNKNOWN")

    def test_environment_and_input_drift_rejected(self):
        c = snapshot(F)
        c["environment_sha"] = H
        with self.assertRaises(SemanticContractError):
            compare_observations(snapshot(A), c, base_sha=A, candidate_sha=F)
        c = snapshot(F)
        c["cases"][0]["input_sha"] = H
        with self.assertRaises(SemanticContractError):
            compare_observations(snapshot(A), c, base_sha=A, candidate_sha=F)

    def test_missing_side_effects_dimension_rejected(self):
        c = snapshot(F)
        c["captured_dimensions"].remove("side_effects")
        with self.assertRaises(SemanticContractError):
            compare_observations(snapshot(A), c, base_sha=A, candidate_sha=F)


if __name__ == "__main__":
    unittest.main()
