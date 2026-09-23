from __future__ import annotations

import json
import unittest
from pathlib import Path

from chatgpt_operation.skill_catalog import (
    SkillCatalogError,
    resolve_triggers,
    validate_catalog,
)


CATALOG_PATH = Path("skills/catalog.json")


class SkillCatalogTests(unittest.TestCase):
    def catalog(self) -> dict:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_catalog_is_valid(self):
        skills = validate_catalog(self.catalog())
        self.assertGreaterEqual(len(skills), 10)

    def test_every_catalog_path_exists(self):
        for skill in validate_catalog(self.catalog()):
            self.assertTrue(Path(skill["path"]).is_file(), skill["path"])

    def test_actions_execution_is_immediately_resolvable(self):
        result = resolve_triggers(
            self.catalog(), ["GITHUB_ACTIONS_EXECUTION"]
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(
            result["skills"],
            [
                {
                    "name": "github-actions-execution",
                    "path": "skills/github-actions-execution/README.md",
                }
            ],
        )

    def test_scheduled_controller_resolves_composed_skills(self):
        result = resolve_triggers(
            self.catalog(), ["SCHEDULED_CONTROLLER"]
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(
            [item["name"] for item in result["skills"]],
            [
                "state-refresh",
                "controller-throughput",
                "controller-lifecycle",
            ],
        )

    def test_unknown_trigger_fails_closed(self):
        result = resolve_triggers(self.catalog(), ["NOT_A_REAL_TRIGGER"])
        self.assertEqual(result["status"], "TRIGGER_UNRESOLVED")
        self.assertEqual(
            result["unresolved_triggers"], ["NOT_A_REAL_TRIGGER"]
        )

    def test_duplicate_skill_name_fails_closed(self):
        catalog = self.catalog()
        catalog["skills"].append(dict(catalog["skills"][0]))
        with self.assertRaises(SkillCatalogError):
            validate_catalog(catalog)


if __name__ == "__main__":
    unittest.main()
