import json
import tempfile
import unittest
from pathlib import Path

from chatgpt_operation.skills.contracts import (
    SkillContractError,
    invoke_contract,
    resolve_capability,
    validate_catalog,
)


class SkillContractTests(unittest.TestCase):
    def test_repository_catalog_resolves_every_declared_contract(self):
        result = validate_catalog("skills/catalog.json")
        self.assertEqual(result["status"], "PASS")
        self.assertIn("github-native-dispatch", result["resolved_contracts"])
        self.assertIn("decision-guard", result["resolved_contracts"])

    def test_unbound_contract_fails_closed(self):
        payload = {
            "schema_version": 1,
            "skills": [{"name": "broken", "contracts": ["not-implemented"]}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(SkillContractError):
                validate_catalog(path)

    def test_invocation_emits_execution_evidence(self):
        result, evidence = invoke_contract("implementation-state")
        self.assertEqual(result.capabilities, {})
        self.assertTrue(evidence.contract_loaded)
        self.assertTrue(evidence.contract_executed)
        self.assertTrue(evidence.contract_passed)

    def test_missing_native_dispatch_resolves_to_skill_not_blocked(self):
        resolution = resolve_capability(
            "GITHUB_WORKFLOW_DISPATCH", native_available=False
        )
        self.assertEqual(resolution.provider, "skill")
        self.assertEqual(resolution.contract, "github-native-dispatch")

    def test_native_dispatch_can_be_used_when_available(self):
        resolution = resolve_capability(
            "GITHUB_WORKFLOW_DISPATCH", native_available=True
        )
        self.assertEqual(resolution.provider, "native")
        self.assertIsNone(resolution.contract)

    def test_truly_unbound_capability_fails_closed(self):
        with self.assertRaises(SkillContractError):
            resolve_capability("UNBOUND_CAPABILITY", native_available=False)


if __name__ == "__main__":
    unittest.main()
