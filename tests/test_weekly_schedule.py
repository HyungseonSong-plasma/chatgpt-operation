import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from chatgpt_operation.weekly_schedule import (
    CANONICAL_TIMEZONE,
    SCHEDULER_CAPABILITY,
    SCHEDULER_CRON,
    SCHEDULER_WORKFLOW,
    canonical_slot,
    phase_for_day,
    scheduled_runtime_reasoning_contract,
)


class WeeklyScheduleTests(unittest.TestCase):
    def test_phase_mapping_is_mon_fri_sat_sun(self):
        days=[date(2026,9,21+i) for i in range(7)]
        self.assertEqual(
            [phase_for_day(day) for day in days],
            ["collect","collect","collect","collect","collect","analyze","close"],
        )

    def test_existing_bootstrap_is_the_durable_scheduler_contract(self):
        contract=scheduled_runtime_reasoning_contract(
            datetime(2026,9,28,6,55,tzinfo=timezone.utc)
        )
        self.assertTrue(contract["existing_durable_scheduler"])
        self.assertFalse(contract["workflow_file_mutation_required"])
        self.assertTrue(contract["code_owned_phase_routing"])
        self.assertEqual(contract["capability"],SCHEDULER_CAPABILITY)
        self.assertEqual(contract["workflow"],SCHEDULER_WORKFLOW)
        self.assertEqual(contract["cron"],SCHEDULER_CRON)
        self.assertEqual(contract["canonical_timezone"],CANONICAL_TIMEZONE)
        self.assertEqual(contract["current_slot"]["phase"],"collect")
        workflow=Path(SCHEDULER_WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("schedule:",workflow)
        self.assertIn("cron: '9 * * * *'",workflow)

    def test_naive_time_is_normalized_to_utc_slot(self):
        slot=canonical_slot(datetime(2026,10,4,12,0))
        self.assertEqual(slot["canonical_timezone"],"UTC")
        self.assertEqual(slot["phase"],"close")
        self.assertEqual(slot["iso_week"],"2026-W40")


if __name__=="__main__":
    unittest.main()
