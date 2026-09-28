import unittest
from datetime import date, datetime, timezone

from chatgpt_operation.weekly_schedule import (
    CANONICAL_TIMEZONE,
    SCHEDULER_CAPABILITY,
    SCHEDULER_WORKFLOW,
    canonical_slot,
    existing_scheduler_surfaces,
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
        surfaces=existing_scheduler_surfaces()
        self.assertEqual(len(surfaces),1)
        self.assertEqual(surfaces[0]["workflow"],SCHEDULER_WORKFLOW)
        self.assertEqual(surfaces[0]["event"],"schedule")
        self.assertFalse(surfaces[0]["mutation_required"])

        contract=scheduled_runtime_reasoning_contract(
            datetime(2026,9,28,6,55,tzinfo=timezone.utc),
            scheduler_surfaces=surfaces,
        )
        self.assertTrue(contract["existing_durable_scheduler"])
        self.assertFalse(contract["workflow_file_mutation_required"])
        self.assertTrue(contract["code_owned_phase_routing"])
        self.assertEqual(contract["capability"],SCHEDULER_CAPABILITY)
        self.assertEqual(contract["workflow"],SCHEDULER_WORKFLOW)
        self.assertEqual(contract["cron"],surfaces[0]["cron"])
        self.assertEqual(contract["canonical_timezone"],CANONICAL_TIMEZONE)
        self.assertEqual(contract["current_slot"]["phase"],"collect")
        self.assertEqual(contract["observed_scheduler_surfaces"],surfaces)

    def test_contract_uses_observed_cron_without_a_policy_copy(self):
        surfaces=[{
            "workflow":SCHEDULER_WORKFLOW,
            "event":"schedule",
            "cron":"37 4 * * *",
            "mutation_required":False,
        }]
        contract=scheduled_runtime_reasoning_contract(
            datetime(2026,9,28,6,55,tzinfo=timezone.utc),
            scheduler_surfaces=surfaces,
        )
        self.assertTrue(contract["existing_durable_scheduler"])
        self.assertEqual(contract["cron"],surfaces[0]["cron"])

    def test_naive_time_is_normalized_to_utc_slot(self):
        slot=canonical_slot(datetime(2026,10,4,12,0))
        self.assertEqual(slot["canonical_timezone"],"UTC")
        self.assertEqual(slot["phase"],"close")
        self.assertEqual(slot["iso_week"],"2026-W40")


if __name__=="__main__":
    unittest.main()
