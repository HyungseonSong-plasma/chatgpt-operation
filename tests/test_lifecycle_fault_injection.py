import unittest

from chatgpt_operation.controller.invariants import ContinuationKind
from chatgpt_operation.controller.lifecycle_scenario import LifecycleScenario
from chatgpt_operation.controller.research import ResearchStage, ResearchState


class LifecycleFaultInjectionTests(unittest.TestCase):
    def scenario(self):
        value = LifecycleScenario(ResearchState("fault-injection", "test scientific lifecycle"))
        value.establish_hypothesis("electron transport closure causes the discrepancy")
        value.design_experiment("compare baseline and closure-enabled lanes")
        value.record_test("closure lane reduces error and passes discriminator")
        return value

    def test_final_write_blocker_does_not_erase_scientific_work(self):
        scenario = self.scenario()

        def blocked_writer(_):
            raise OSError("simulated write permission blocker")

        outcome = scenario.finalize(blocked_writer)

        self.assertEqual(outcome.kind, ContinuationKind.RETRY)
        self.assertEqual(scenario.state.stage, ResearchStage.DECIDE)
        self.assertEqual(
            scenario.evidence.hypothesis,
            "electron transport closure causes the discrepancy",
        )
        self.assertEqual(
            scenario.evidence.experiment,
            "compare baseline and closure-enabled lanes",
        )
        self.assertEqual(
            scenario.evidence.test_result,
            "closure lane reduces error and passes discriminator",
        )
        self.assertIsNone(scenario.evidence.final_write)
        self.assertIn("final_write_blocked", scenario.evidence.events)

    def test_blocked_final_write_resumes_without_repeating_science(self):
        scenario = self.scenario()
        before = list(scenario.evidence.events)

        def blocked_writer(_):
            raise OSError("simulated connector write blocker")

        first = scenario.finalize(blocked_writer)
        self.assertEqual(first.kind, ContinuationKind.RETRY)

        writes = []
        second = scenario.resume_finalization(writes.append)

        self.assertEqual(second.kind, ContinuationKind.COMPLETE)
        self.assertEqual(scenario.state.stage, ResearchStage.COMPLETE)
        self.assertEqual(writes, ["closure lane reduces error and passes discriminator"])
        self.assertEqual(scenario.evidence.events[:3], before)
        self.assertEqual(
            scenario.evidence.events.count("hypothesis"), 1,
            "resume must not regenerate the hypothesis",
        )
        self.assertEqual(
            scenario.evidence.events.count("experiment"), 1,
            "resume must not redesign the experiment",
        )
        self.assertEqual(
            scenario.evidence.events.count("test"), 1,
            "resume must not rerun the validated test",
        )

    def test_replayed_successful_finalization_is_idempotent(self):
        scenario = self.scenario()
        writes = []
        self.assertEqual(scenario.finalize(writes.append).kind, ContinuationKind.COMPLETE)
        self.assertEqual(scenario.resume_finalization(writes.append).kind, ContinuationKind.COMPLETE)
        self.assertEqual(len(writes), 1)


if __name__ == "__main__":
    unittest.main()
