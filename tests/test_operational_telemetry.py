import copy
import json
from pathlib import Path
import tempfile
import unittest

from chatgpt_operation.controller.skill_telemetry import (
    MARKER,
    build_run_record,
    merge_run,
)
from chatgpt_operation.weekly_maintenance import (
    classify_failure,
    dedupe_failures,
    full_week_dry_run,
    select_candidates,
    summarize_week,
)


def cycle(*, kind="action", command=True):
    return {
        "schema_version":4,
        "trigger":{},
        "selected_work":{"kind":kind},
        "issue_planning":None,
        "admission_write":None,
        "state_write":{"method":"PATCH"} if kind!="idle" else None,
        "execution_command":{"kind":"dispatch_action"} if command else None,
    }


def failure(
    *,
    run_id=10,
    run_attempt=1,
    signature="repeat",
    external=False,
    central=True,
):
    return {
        "repository":"HyungseonSong-plasma/moose-test-repo",
        "workflow":"Repository CI",
        "run_id":run_id,
        "run_attempt":run_attempt,
        "job":"test",
        "step":"contract",
        "head_sha":"a"*40,
        "event":"push",
        "observed_at":"2026-09-22T06:00:00Z",
        "conclusion":"failure",
        "failure_signature":signature,
        "evidence_flags":{
            "external_dependency":external,
            "central_skill_contract":central and not external,
            "workflow_configuration":False,
            "repository_test":False,
            "transient_infrastructure":False,
        },
    }


class SkillGovernanceTelemetryTests(unittest.TestCase):
    def test_controller_run_records_real_consultation_and_governance(self):
        record=build_run_record(
            cycle(),
            event_name="pull_request",
            run_id=100,
            head_sha="a"*40,
            repository="HyungseonSong-plasma/chatgpt-operation",
        )
        self.assertEqual(record["resolved_skills"],["research-controller"])
        self.assertEqual(record["consulted_skills"],["research-controller"])
        self.assertEqual(record["applied_skills"],["research-controller"])
        self.assertEqual(
            record["governed_actions"],record["total_material_actions"]
        )
        evidence=record["applied_skill_evidence"][0]
        self.assertEqual(evidence["path"],"skills/research-controller/README.md")

    def test_schedule_exposes_resolved_but_unused_skills(self):
        record=build_run_record(
            cycle(),
            event_name="schedule",
            run_id=101,
            head_sha="b"*40,
            repository="HyungseonSong-plasma/chatgpt-operation",
        )
        self.assertIn("state-refresh",record["resolved_skills"])
        self.assertIn("controller-throughput",record["resolved_skills"])
        self.assertIn("controller-lifecycle",record["resolved_skills"])
        self.assertEqual(record["consulted_skills"],["research-controller"])
        self.assertIn("state-refresh",record["unused_resolved_skills"])

    def test_zero_denominators_are_null_not_invented_scores(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"catalog.json"
            path.write_text(
                json.dumps({"schema_version":1,"skills":[]}),
                encoding="utf-8",
            )
            record=build_run_record(
                cycle(kind="idle",command=False),
                event_name="workflow_dispatch",
                run_id=102,
                head_sha="c"*40,
                repository="o/r",
                catalog_path=path,
                repository_root=root,
            )
        self.assertIsNone(record["metrics"]["resolution_coverage"])
        self.assertIsNone(record["metrics"]["application_rate"])
        self.assertIsNone(record["metrics"]["action_governance_rate"])

    def test_rolling_comment_deduplicates_run_and_reports_trailing_five(self):
        body=None
        for run_id in range(1,6):
            record=build_run_record(
                cycle(),
                event_name="pull_request",
                run_id=run_id,
                head_sha="d"*40,
                repository="HyungseonSong-plasma/chatgpt-operation",
            )
            body,summary=merge_run(body,record)
        replay=build_run_record(
            cycle(),
            event_name="pull_request",
            run_id=5,
            head_sha="d"*40,
            repository="HyungseonSong-plasma/chatgpt-operation",
        )
        body,summary=merge_run(body,replay)
        self.assertEqual(summary["run_count"],5)
        self.assertIsNotNone(summary["trailing_5_run_averages"])
        self.assertIn(MARKER,body)


class WeeklyMaintenanceTests(unittest.TestCase):
    def test_retry_is_deduplicated_by_logical_failure_identity(self):
        first=failure(run_attempt=1)
        retry=failure(run_attempt=2)
        items,duplicates=dedupe_failures([first,retry])
        self.assertEqual(len(items),1)
        self.assertEqual(duplicates,1)
        self.assertEqual(items[0]["run_attempt"],2)

    def test_external_dependency_requires_explicit_evidence(self):
        external=failure(signature="http-502",external=True,central=False)
        self.assertEqual(
            classify_failure(external),"EXTERNAL_DEPENDENCY_FAILURE"
        )
        unknown=copy.deepcopy(external)
        unknown["evidence_flags"]={key:False for key in external["evidence_flags"]}
        self.assertEqual(classify_failure(unknown),"UNKNOWN")

    def test_candidate_requires_repeated_actionable_evidence(self):
        failures=[
            failure(run_id=10,signature="central"),
            failure(run_id=11,signature="central"),
            failure(run_id=12,signature="external",external=True,central=False),
            failure(run_id=13,signature="external",external=True,central=False),
        ]
        summary=summarize_week([],failures,known_skills=[])
        candidates=select_candidates(summary)
        self.assertEqual([x["signature"] for x in candidates],["central"])
        self.assertEqual(
            summary["workflow_failures"]["by_class"]["EXTERNAL_DEPENDENCY_FAILURE"],
            2,
        )

    def test_full_mon_sun_dry_run_has_no_silent_auto_merge(self):
        result=full_week_dry_run()
        self.assertEqual(
            [x["phase"] for x in result["days"]],
            ["collect","collect","collect","collect","collect","analyze","close"],
        )
        proposed=result["sunday"]["improvements_proposed"]
        self.assertTrue(proposed)
        self.assertTrue(all(not item["pr"]["auto_merge"] for item in proposed))
        self.assertIn(
            "inl-conda-http-502",
            result["sunday"]["known_external_failures_not_actionable_in_skills"],
        )

    def test_normal_package_init_does_not_load_weekly_telemetry(self):
        text=Path("src/chatgpt_operation/__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("weekly_maintenance",text)
        self.assertNotIn("skill_telemetry",text)


if __name__=="__main__":
    unittest.main()
