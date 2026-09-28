import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from chatgpt_operation.science import (
    DevelopmentState,
    ExperimentIntent,
    RunEnvelope,
    UnresolvedPolicyError,
    compile_execution_plan,
    default_capabilities,
    read_run_envelope,
    synthesize_policy,
    write_run_envelope,
)
from chatgpt_operation.science.contract import self_test as contract_self_test
from chatgpt_operation.science.errors import (
    AttributionConfidence,
    AttributionSignals,
    ErrorCategory,
    classify_attribution,
    error_fingerprint,
)


class ScientificSemanticsTests(unittest.TestCase):
    def test_promoted_records_remain_immutable(self):
        state=DevelopmentState(state_id="state:1",case_id="case:1")
        with self.assertRaises(FrozenInstanceError):
            state.state_id="state:2"

    def test_policy_synthesis_and_execution_compile_are_deterministic(self):
        state=DevelopmentState(
            state_id="state:plasma",
            case_id="case:plasma",
            system=(("signed_heavy_charge_number_density_m3",2.5e16),),
        )
        intent=ExperimentIntent(
            intent_id="intent:gummel",
            experiment_id="gummel",
            objective="discriminate controlled transport behavior",
            target_ids=("gummel-convergence",),
            requested_capabilities=(
                "electron_energy_diffusion",
                "quasi_neutral_initialization",
            ),
            parameters=(("diffusivity",0.25),),
            constraint_ids=("freeze-heavy-state",),
            requested_observations=("residual",),
            execution_bounds=(("max_cases",3),),
        )
        first=synthesize_policy(state,intent,default_capabilities())
        second=synthesize_policy(state,intent,default_capabilities())
        self.assertEqual(first,second)
        self.assertFalse(first.unresolved_requirements)
        self.assertEqual(
            dict(first.derived_values)["electron_reference_density_m3"],
            2.5e16,
        )

        plan=compile_execution_plan(first)
        self.assertEqual(plan.source_policy_id,first.policy_id)
        self.assertEqual(len(plan.cases),3)
        self.assertEqual(plan.required_observations,("residual",))
        self.assertTrue(
            all("freeze-heavy-state" in case.held_fixed for case in plan.cases)
        )

    def test_unresolved_capability_fails_closed_before_execution(self):
        state=DevelopmentState(state_id="state:1",case_id="case:1")
        intent=ExperimentIntent(
            intent_id="intent:missing",
            experiment_id="missing",
            objective="require an unavailable capability",
            requested_capabilities=("not-installed",),
        )
        policy=synthesize_policy(state,intent,default_capabilities())
        self.assertEqual(
            policy.unresolved_requirements,
            ("CAPABILITY_GAP:not-installed",),
        )
        with self.assertRaisesRegex(
            UnresolvedPolicyError,
            "unresolved requirements remain",
        ):
            compile_execution_plan(policy)

    def test_run_envelope_round_trips_reference_only_lineage(self):
        envelope=RunEnvelope(
            run_id="run-1",
            experiment_id="exp-1",
            protocol="qualified",
            source_revision="a"*40,
        )
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"run-envelope.json"
            write_run_envelope(path,envelope)
            self.assertEqual(read_run_envelope(path),envelope)

    def test_error_attribution_is_evidence_driven_and_conflicts_fail_closed(self):
        code=classify_attribution(AttributionSignals(
            contract_conformant=True,
            reproducible_runtime_failure=True,
            isolated_code_owner="solver",
        ))
        self.assertEqual(code.category,ErrorCategory.CODE_ERROR)
        self.assertEqual(code.confidence,AttributionConfidence.CONFIRMED)

        conflict=classify_attribution(AttributionSignals(
            user_controlled_contract_violation=True,
            assistant_generated_contract_violation=True,
        ))
        self.assertEqual(conflict.category,ErrorCategory.UNCLASSIFIED)
        self.assertEqual(conflict.confidence,AttributionConfidence.UNRESOLVED)

        self.assertEqual(
            error_fingerprint(
                category="CODE_ERROR",
                error_code="E1",
                source_layer="runtime",
                signature="same",
            ),
            error_fingerprint(
                category="CODE_ERROR",
                error_code="E1",
                source_layer="runtime",
                signature="same",
            ),
        )

    def test_promoted_scientific_execution_contract_self_test(self):
        self.assertEqual(contract_self_test(),0)


if __name__=="__main__":
    unittest.main()
