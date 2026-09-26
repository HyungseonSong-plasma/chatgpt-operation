import pathlib
import tempfile
import unittest
from chatgpt_operation.controller.bootstrap import load_pending, BootstrapError


class SamuelBootstrapTests(unittest.TestCase):
    def test_repository_queue_contains_live_qualification(self):
        pending=load_pending("automation/samuel/bootstrap.json")
        self.assertEqual([x.work_id for x in pending], ["issue-44-write-blocker-qualification"])
        self.assertEqual(pending[0].workflow, "samuel-write-blocker-qualification.yml")

    def test_schedule_is_root_trigger_not_plan_injection(self):
        text=pathlib.Path(".github/workflows/samuel-bootstrap.yml").read_text()
        self.assertIn("schedule:", text)
        self.assertIn("actions: write", text)
        self.assertIn("dispatch_and_wait", text)
        self.assertNotIn("plan_json", text)

    def test_duplicate_work_ids_fail_closed(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as f:
            f.write('{"schema_version":1,"work":[{"work_id":"x","kind":"workflow","workflow":"a"},{"work_id":"x","kind":"workflow","workflow":"b"}]}')
            f.flush()
            with self.assertRaises(BootstrapError):
                load_pending(f.name)


if __name__ == "__main__":
    unittest.main()
