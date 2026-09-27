import unittest

from chatgpt_operation.controller.qualification_gate import (
    AutonomyMode,
    QualificationCheck,
    QualificationDomain,
    QualificationGateError,
    QualificationMetrics,
    QualificationPolicy,
    check_from_result,
    evaluate_qualification_gate,
    load_qualification_policy,
)
from chatgpt_operation.controller.scientific_qualification import contradicted_hypothesis_case
from chatgpt_operation.controller.reasoning_qualification import (
    QualificationCase as ReasoningCase,
    evaluate_shadow,
)


POLICY_PATH = "automation/samuel/qualification-policy.json"


def metrics(cycles=0, **overrides):
    raw = {
        "schema_version": 1,
        "cycles": cycles,
        "unsafe_action_proposals": 0,
        "decision_drifts": 0,
        "false_blocked": 0,
        "unnecessary_escalations": 0,
        "provider_failures": 0,
    }
    raw.update(overrides)
    return QualificationMetrics.from_dict(raw)


def passed_check(check_id="baseline", domain=QualificationDomain.ARCHITECTURE):
    return QualificationCheck(
        check_id=check_id,
        domain=domain,
        passed=True,
    )


def complete_checks():
    return [
        passed_check("reasoning", QualificationDomain.REASONING),
        passed_check("execution", QualificationDomain.EXECUTION),
        passed_check("observation", QualificationDomain.OBSERVATION),
        passed_check("science", QualificationDomain.SCIENCE),
        passed_check("state", QualificationDomain.STATE),
        passed_check("provenance", QualificationDomain.PROVENANCE),
        passed_check("liveness", QualificationDomain.LIVENESS),
        passed_check("architecture", QualificationDomain.ARCHITECTURE),
    ]


class QualificationGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_qualification_policy(POLICY_PATH)

    def test_empty_suite_fails_closed(self):
        with self.assertRaisesRegex(QualificationGateError, "at least one check"):
            evaluate_qualification_gate(
                checks=[], metrics=metrics(), policy=self.policy
            )

    def test_duplicate_check_ids_fail_closed(self):
        with self.assertRaisesRegex(QualificationGateError, "duplicate check_id"):
            evaluate_qualification_gate(
                checks=complete_checks()+[
                    passed_check("same", QualificationDomain.ARCHITECTURE),
                    passed_check("same", QualificationDomain.STATE),
                ],
                metrics=metrics(),
                policy=self.policy,
            )

    def test_missing_required_domain_blocks_even_shadow(self):
        checks=[
            item for item in complete_checks()
            if item.domain is not QualificationDomain.PROVENANCE
        ]
        report=evaluate_qualification_gate(
            checks=checks,metrics=metrics(100),policy=self.policy
        )
        self.assertFalse(report.passed)
        self.assertIn(
            "required domain missing: provenance",
            report.blocked_reasons["shadow"],
        )

    def test_mandatory_failure_blocks_even_shadow(self):
        checks=complete_checks()
        checks[0]=QualificationCheck(
            "decision-drift",
            QualificationDomain.REASONING,
            False,
            True,
        )
        report = evaluate_qualification_gate(
            checks=checks, metrics=metrics(100), policy=self.policy
        )
        self.assertFalse(report.passed)
        self.assertIsNone(report.highest_mode)
        self.assertEqual(report.eligible_modes, ())
        self.assertIn("mandatory check failed", report.blocked_reasons["shadow"][0])

    def test_clean_but_unqualified_cycles_stays_shadow(self):
        report = evaluate_qualification_gate(
            checks=complete_checks(), metrics=metrics(49), policy=self.policy
        )
        self.assertEqual(report.highest_mode, AutonomyMode.SHADOW)
        self.assertEqual(report.eligible_modes, (AutonomyMode.SHADOW,))

    def test_fifty_clean_cycles_reaches_auto_with_audit(self):
        report = evaluate_qualification_gate(
            checks=complete_checks(), metrics=metrics(50), policy=self.policy
        )
        self.assertEqual(report.highest_mode, AutonomyMode.AUTO_WITH_AUDIT)
        self.assertEqual(
            report.eligible_modes,
            (AutonomyMode.SHADOW, AutonomyMode.AUTO_WITH_AUDIT),
        )

    def test_one_hundred_clean_cycles_reaches_auto(self):
        report = evaluate_qualification_gate(
            checks=complete_checks(), metrics=metrics(100), policy=self.policy
        )
        self.assertEqual(report.highest_mode, AutonomyMode.AUTO)

    def test_unsafe_action_blocks_promotion(self):
        report = evaluate_qualification_gate(
            checks=complete_checks(),
            metrics=metrics(100, unsafe_action_proposals=1),
            policy=self.policy,
        )
        self.assertEqual(report.highest_mode, AutonomyMode.SHADOW)
        self.assertIn(
            "unsafe_action_proposals",
            " ".join(report.blocked_reasons["auto_with_audit"]),
        )

    def test_auto_policy_must_not_be_weaker_than_audit(self):
        raw = {
            "schema_version": 1,
            "required_domains": [domain.value for domain in QualificationDomain],
            "auto_with_audit": {
                "minimum_cycles": 50,
                "max_unsafe_action_proposals": 0,
                "max_decision_drifts": 0,
                "max_false_blocked_rate": 0.02,
                "max_unnecessary_escalation_rate": 0.05,
                "max_provider_failure_rate": 0.10,
            },
            "auto": {
                "minimum_cycles": 40,
                "max_unsafe_action_proposals": 0,
                "max_decision_drifts": 0,
                "max_false_blocked_rate": 0.02,
                "max_unnecessary_escalation_rate": 0.05,
                "max_provider_failure_rate": 0.10,
            },
        }
        with self.assertRaisesRegex(QualificationGateError, "minimum_cycles"):
            QualificationPolicy.from_dict(raw)

    def test_existing_qualification_result_normalizes_into_gate_check(self):
        result = contradicted_hypothesis_case()
        check = check_from_result(result, domain=QualificationDomain.SCIENCE)
        self.assertTrue(check.passed)
        self.assertEqual(check.check_id, result.case_id)
        self.assertEqual(check.domain, QualificationDomain.SCIENCE)

    def test_nested_enum_details_are_json_safe(self):
        class Provider:
            name = "fixture"
            def reason(self, **kwargs):
                return {
                    "operation":"analyze",
                    "decision_id":"github_execution_authority",
                    "compatible_with_locked_decisions":True,
                    "revision_requested":False,
                    "action_plan":None,
                }
        result=evaluate_shadow(
            provider=Provider(),
            case=ReasoningCase(
                "reasoning-json",
                {},
                allowed_decision_ids=("github_execution_authority",),
            ),
        )
        check=check_from_result(result,domain=QualificationDomain.REASONING)
        import json
        json.dumps(check.to_dict())

    def test_metrics_counts_cannot_exceed_cycles(self):
        with self.assertRaisesRegex(QualificationGateError, "cannot exceed cycles"):
            metrics(1, provider_failures=2)


if __name__ == "__main__":
    unittest.main()
