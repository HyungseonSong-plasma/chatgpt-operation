import tempfile
import unittest
from pathlib import Path

from chatgpt_operation.controller.decisions import (
    ArchitectureDecision,
    DecisionError,
    DecisionGuard,
    DecisionRegistry,
    DecisionStatus,
    GuardOutcome,
    ReasoningProposal,
)
from chatgpt_operation.controller.envelope import (
    ReasoningEnvelopeError,
    build_reasoning_envelope,
)
from chatgpt_operation.controller.implementation import (
    Capability,
    CapabilityStatus,
    ImplementationState,
)


def accepted(version=1, supersedes=None):
    return ArchitectureDecision(
        decision_id="github_execution_authority",
        version=version,
        status=DecisionStatus.ACCEPTED,
        statement="LLM is not the primary repository mutation executor",
        invariants=("native_executor_owns_mutation",),
        evidence=("issue-41",),
        accepted_at="2026-09-26T00:00:00Z",
        supersedes=supersedes,
    )


class DecisionRegistryTests(unittest.TestCase):
    def test_decision_versions_are_immutable(self):
        registry = DecisionRegistry()
        registry.register(accepted())
        with self.assertRaises(DecisionError):
            registry.register(accepted())

    def test_revision_must_explicitly_supersede_current(self):
        registry = DecisionRegistry()
        registry.register(accepted())
        with self.assertRaises(DecisionError):
            registry.register(accepted(version=2))

    def test_registry_round_trip_preserves_accepted_decision(self):
        registry = DecisionRegistry()
        registry.register(accepted())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.json"
            registry.save(path)
            loaded = DecisionRegistry.load(path)
        self.assertEqual(loaded.current("github_execution_authority"), accepted())


class ImplementationStateTests(unittest.TestCase):
    def test_accepted_architecture_does_not_imply_implementation(self):
        state = ImplementationState()
        state.record(Capability("action_plan", CapabilityStatus.VERIFIED, ("ci-82",)))
        self.assertEqual(
            state.gaps(("action_plan", "native_github_executor")),
            ("native_github_executor",),
        )


class ReasoningEnvelopeTests(unittest.TestCase):
    def test_envelope_locks_decisions_and_reports_gap(self):
        registry = DecisionRegistry()
        registry.register(accepted())
        state = ImplementationState()
        envelope = build_reasoning_envelope(
            goal="resolve connector write blocker",
            observations=("connector write blocked",),
            registry=registry,
            implementation=state,
            required_capabilities=("native_github_executor",),
            allowed_reasoning_operations=("implement_gap", "propose_revision"),
            required_outputs=("proposal",),
        )
        self.assertEqual(envelope.locked_decisions[0].decision_id, "github_execution_authority")
        self.assertEqual(envelope.implementation_gaps, ("native_github_executor",))

    def test_envelope_fails_closed_without_accepted_decision(self):
        with self.assertRaises(ReasoningEnvelopeError):
            build_reasoning_envelope(
                goal="x",
                observations=(),
                registry=DecisionRegistry(),
                implementation=ImplementationState(),
                required_capabilities=(),
                allowed_reasoning_operations=("analyze",),
                required_outputs=("proposal",),
            )


class DecisionGuardTests(unittest.TestCase):
    def test_silent_conflict_is_rejected(self):
        result = DecisionGuard().validate(
            ReasoningProposal(
                operation="analyze",
                decision_id="github_execution_authority",
                compatible_with_locked_decisions=False,
            ),
            (accepted(),),
        )
        self.assertEqual(result.outcome, GuardOutcome.REJECTED)

    def test_explicit_conflict_becomes_revision_required(self):
        result = DecisionGuard().validate(
            ReasoningProposal(
                operation="analyze",
                decision_id="github_execution_authority",
                compatible_with_locked_decisions=False,
                revision_requested=True,
            ),
            (accepted(),),
        )
        self.assertEqual(result.outcome, GuardOutcome.REVISION_REQUIRED)

    def test_gap_work_is_distinct_from_architecture_revision(self):
        result = DecisionGuard().validate(
            ReasoningProposal(
                operation="implement_gap",
                decision_id="github_execution_authority",
            ),
            (accepted(),),
            ("native_github_executor",),
        )
        self.assertEqual(result.outcome, GuardOutcome.IMPLEMENT_GAP)


if __name__ == "__main__":
    unittest.main()
