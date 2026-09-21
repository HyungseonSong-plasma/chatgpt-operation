import unittest
from chatgpt_operation.telemetry import TelemetryError, aggregate, identity

SHA = "a" * 40

def event(**changes):
    value = {
        "event": "skill_activation",
        "activation_id": "run-42:init:state-refresh",
        "skill": "state-refresh",
        "skill_path": "skills/state-refresh/README.md",
        "consumer": "HyungseonSong-plasma/moose-test-repo",
        "central_revision": SHA,
        "trigger": "INIT",
        "observed_at": "2026-09-21T08:00:00Z",
    }
    value.update(changes)
    return value

class TelemetryTests(unittest.TestCase):
    def test_retry_is_deduplicated_even_if_retry_timestamp_changes(self):
        first = event()
        retry = event(observed_at="2026-09-21T08:01:00Z")
        self.assertEqual(identity(first), identity(retry))
        result = aggregate([first, retry], known_skills=["state-refresh", "governed-work"])
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["skills_with_zero_observed_activation"], ["governed-work"])

    def test_distinct_activation_ids_count(self):
        result = aggregate([event(), event(activation_id="run-43:init:state-refresh")])
        self.assertEqual(result["event_count"], 2)

    def test_exact_revision_is_required(self):
        with self.assertRaises(TelemetryError):
            aggregate([event(central_revision="main")])

    def test_aggregate_dimensions(self):
        result = aggregate([event()])
        self.assertEqual(result["activations_by_skill_day"], {"state-refresh|2026-09-21": 1})
        self.assertEqual(result["activations_by_trigger"], {"INIT": 1})
        self.assertEqual(result["total_activations_by_week"], {"2026-W39": 1})

if __name__ == "__main__":
    unittest.main()
