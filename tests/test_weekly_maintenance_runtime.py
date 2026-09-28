import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from chatgpt_operation.weekly_maintenance_runtime import (
    CONSUMERS,
    GitHubPublicActions,
    collect_all_failures,
    execute_phase,
)


class FakeActions:
    def __init__(self):
        self.repo_index={repo:index for index,repo in enumerate(CONSUMERS, start=1)}

    def json(self,path):
        if "/actions/runs?" in path:
            repo=path.split("/repos/",1)[1].split("/actions/",1)[0]
            index=self.repo_index[repo]
            return {
                "workflow_runs":[{
                    "id":1000+index,
                    "name":"Consumer CI",
                    "event":"push",
                    "conclusion":"failure",
                    "head_sha":str(index)*40,
                    "run_attempt":1,
                    "created_at":"2026-09-24T10:00:00Z",
                    "updated_at":"2026-09-24T10:02:00Z",
                }]
            }
        if path.endswith("/jobs?filter=latest&per_page=100"):
            run_id=int(path.split("/actions/runs/",1)[1].split("/",1)[0])
            return {
                "jobs":[{
                    "id":run_id+10000,
                    "name":"test",
                    "conclusion":"failure",
                    "steps":[{
                        "name":"Run consumer tests",
                        "conclusion":"failure",
                    }],
                }]
            }
        raise AssertionError("unexpected JSON path: "+path)

    def text_or_none(self,path):
        # sol-adapter-moose maps to the second run id: 1002 / job 11002.
        if "/actions/jobs/11002/logs" in path:
            return "CondaHTTPError: HTTP 502 BAD GATEWAY from external package service"
        return "AssertionError: consumer contract tests failed"


class WeeklyMaintenanceRuntimeTests(unittest.TestCase):
    def test_collect_observes_all_current_consumers_and_preserves_raw_evidence(self):
        client=FakeActions()
        with tempfile.TemporaryDirectory() as root:
            result=execute_phase(
                "collect",
                client=client,
                output_dir=root,
                as_of=datetime(2026,9,25,12,0,tzinfo=timezone.utc),
                lookback_days=2,
            )
            self.assertEqual(
                set(result["workflow_failure_sources"]),
                set(CONSUMERS),
            )
            self.assertTrue(all(
                item["status"]=="observed"
                for item in result["workflow_failure_sources"].values()
            ))
            raw=[
                json.loads(line)
                for line in (
                    Path(root)/"raw"/"workflow-failures.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertEqual(len(raw),3)
            self.assertEqual(
                {item["repository"] for item in raw},
                set(CONSUMERS),
            )
            sol=next(
                item for item in raw
                if item["repository"]=="HyungseonSong-plasma/sol-adapter-moose"
            )
            self.assertTrue(sol["evidence_flags"]["external_dependency"])
            self.assertFalse(sol["evidence_flags"]["repository_test"])
            self.assertEqual(
                result["skill_telemetry"]["status"],
                "available_zero_events_observed",
            )
            self.assertIn(
                "not evidence of zero Skill usage",
                result["skill_telemetry"]["semantic"],
            )

    def test_analyze_is_reproducible_and_close_only_proposes_reviewable_transactions(self):
        client=FakeActions()
        as_of=datetime(2026,9,26,12,0,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            first=execute_phase(
                "analyze",
                client=client,
                output_dir=Path(root)/"first",
                as_of=as_of,
            )
            second=execute_phase(
                "analyze",
                client=client,
                output_dir=Path(root)/"second",
                as_of=as_of,
            )
            self.assertEqual(first["summary"],second["summary"])
            closed=execute_phase(
                "close",
                client=client,
                output_dir=Path(root)/"close",
                as_of=datetime(2026,9,27,12,0,tzinfo=timezone.utc),
            )
            closure=closed["closure"]
            self.assertFalse(closure["silent_direct_mutation"])
            self.assertTrue(all(
                not item["pr"]["auto_merge"]
                for item in closure["improvements_proposed"]
            ))

    def test_full_mon_sun_dry_run_is_durable_and_mutation_free(self):
        with tempfile.TemporaryDirectory() as root:
            result=execute_phase(
                "dry_run",
                client=FakeActions(),
                output_dir=root,
                as_of=datetime(2026,9,27,12,0,tzinfo=timezone.utc),
            )
            self.assertEqual(
                [item["phase"] for item in result["days"]],
                ["collect","collect","collect","collect","collect","analyze","close"],
            )
            self.assertFalse(result["execution"]["mutation_performed"])
            self.assertEqual(result["execution"]["consumer_scope"],list(CONSUMERS))
            self.assertTrue(
                (Path(root)/"full-week-dry-run.json").is_file()
            )

    def test_trusted_workflow_has_utc_cadence_and_durable_artifact(self):
        workflow=Path(
            ".github/workflows/samuel-weekly-maintenance.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("Canonical timezone: UTC",workflow)
        self.assertIn("17 6 * * 1-5",workflow)
        self.assertIn("27 6 * * 6",workflow)
        self.assertIn("37 6 * * 0",workflow)
        self.assertIn(
            "python3 -m chatgpt_operation.weekly_maintenance_runtime",
            workflow,
        )
        self.assertIn("actions/upload-artifact@v4",workflow)
        self.assertIn("retention-days: 90",workflow)
        self.assertIn("contents: read",workflow)
        self.assertIn("actions: read",workflow)

    def test_trusted_workflow_is_denied_to_runtime_repository_mutation(self):
        policy=json.loads(
            Path(
                "automation/samuel/repository-mutation-policy.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(
            ".github/workflows/samuel-weekly-maintenance.yml",
            policy["mutation"]["file_paths"]["deny"],
        )


class PublicActionsTransportTests(unittest.TestCase):
    def test_fixed_consumer_allowlist_is_exact(self):
        self.assertEqual(
            CONSUMERS,
            (
                "HyungseonSong-plasma/simulation-ontology",
                "HyungseonSong-plasma/sol-adapter-moose",
                "HyungseonSong-plasma/moose-test-repo",
            ),
        )

    def test_transport_does_not_expose_write_methods(self):
        self.assertFalse(hasattr(GitHubPublicActions,"post"))
        self.assertFalse(hasattr(GitHubPublicActions,"put"))
        self.assertFalse(hasattr(GitHubPublicActions,"patch"))
        self.assertFalse(hasattr(GitHubPublicActions,"delete"))


if __name__=="__main__":
    unittest.main()
