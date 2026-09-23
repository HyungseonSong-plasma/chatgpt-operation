from __future__ import annotations

import copy
import unittest

from chatgpt_operation.controller.scientific_discriminator import (
    ScientificDiscriminatorError,
    summary,
    validate_plan,
)


BASE = {
    "schema_version": 1,
    "cycle_id": "seq11",
    "baseline_sha": "1" * 40,
    "baseline_evidence": ["Issue310 Sequence10 result"],
    "objective": {
        "architecture_invariant": "retain Gummel iteration structure",
        "metric": "average fixed-point loops per electron step",
        "target": "O(10) or lower",
        "success_condition": "target reached with frozen-physics parity",
    },
    "frozen_invariants": [
        "plasma physics",
        "electron timestep",
        "heavy timestep",
        "convergence tolerances",
    ],
    "shared_inputs": [
        {
            "id": "baseline-input",
            "evidence": "qualified Sequence08 input state",
            "access": "read_only",
        }
    ],
    "hypotheses": [
        {
            "id": "h1",
            "statement": "Secant first accelerated update uses inconsistent history",
            "mechanism": "history vectors cross physical-timestep ownership",
            "falsifier": "instrumented vectors show consistent ownership and bounded update",
            "prior_evidence": ["Sequence09", "Sequence10"],
        },
        {
            "id": "h2",
            "statement": "A different Gummel accelerator can reduce loop count",
            "mechanism": "multi-vector acceleration improves contraction",
            "falsifier": "isolated accelerator lane does not reduce loop count while preserving parity",
            "prior_evidence": ["Picard 2x stable reference"],
        },
    ],
    "experiments": [
        {
            "id": "e1",
            "hypothesis_id": "h1",
            "lane_id": "lane-h1",
            "base_sha": "1" * 40,
            "branch": "issue-310-h1-seq11",
            "workspace": "work/lane-h1",
            "artifact_namespace": "evidence/seq11/h1",
            "shared_input_ids": ["baseline-input"],
            "mutation_scope": ["MOOSE diagnostic instrumentation only"],
            "discriminating_observables": ["step2 first Secant update norm"],
            "controls": ["same-run Picard reference"],
            "variants": [],
        },
        {
            "id": "e2",
            "hypothesis_id": "h2",
            "lane_id": "lane-h2",
            "base_sha": "1" * 40,
            "branch": "issue-310-h2-seq11",
            "workspace": "work/lane-h2",
            "artifact_namespace": "evidence/seq11/h2",
            "shared_input_ids": ["baseline-input"],
            "mutation_scope": ["alternative accelerator configuration only"],
            "discriminating_observables": ["FP loops per step", "solution parity"],
            "controls": ["same-run Picard reference"],
            "variants": [
                {"id": "v1", "change": "accelerator setting A"},
                {"id": "v2", "change": "accelerator setting B"},
            ],
        },
    ],
}


class ScientificDiscriminatorTests(unittest.TestCase):
    def test_multiple_hypotheses_with_isolated_lanes_are_valid(self):
        result = summary(BASE)
        self.assertEqual(result["status"], "PLAN_VALID")
        self.assertEqual(result["hypothesis_count"], 2)
        self.assertEqual(result["experiment_lane_count"], 2)

    def test_lane_must_start_from_same_baseline(self):
        plan = copy.deepcopy(BASE)
        plan["experiments"][1]["base_sha"] = "2" * 40
        with self.assertRaises(ScientificDiscriminatorError):
            validate_plan(plan)

    def test_branches_must_be_unique(self):
        plan = copy.deepcopy(BASE)
        plan["experiments"][1]["branch"] = plan["experiments"][0]["branch"]
        with self.assertRaises(ScientificDiscriminatorError):
            validate_plan(plan)

    def test_workspaces_must_be_unique(self):
        plan = copy.deepcopy(BASE)
        plan["experiments"][1]["workspace"] = plan["experiments"][0]["workspace"]
        with self.assertRaises(ScientificDiscriminatorError):
            validate_plan(plan)

    def test_artifact_namespaces_must_not_overlap(self):
        plan = copy.deepcopy(BASE)
        plan["experiments"][1]["artifact_namespace"] = "evidence/seq11/h1/sub"
        with self.assertRaises(ScientificDiscriminatorError):
            validate_plan(plan)

    def test_every_hypothesis_requires_an_experiment(self):
        plan = copy.deepcopy(BASE)
        plan["experiments"] = plan["experiments"][:1]
        with self.assertRaises(ScientificDiscriminatorError):
            validate_plan(plan)

    def test_shared_inputs_must_be_read_only(self):
        plan = copy.deepcopy(BASE)
        plan["shared_inputs"][0]["access"] = "read_write"
        with self.assertRaises(ScientificDiscriminatorError):
            validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
