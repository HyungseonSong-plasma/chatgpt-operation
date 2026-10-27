import unittest
from chatgpt_operation.skills.capability_registry import (
    CapabilityRegistryError,
    assert_capability_exhausted,
    resolve_providers,
    validate_registry,
)

class CapabilityRegistryTests(unittest.TestCase):
    def test_merge_chain_is_authoritative_and_deterministic(self):
        providers=resolve_providers("GITHUB_PR_MERGE")
        self.assertEqual([p.name for p in providers],["github-connector","repository-native"])
        self.assertEqual(providers[1].workflow,".github/workflows/samuel-controller.yml")
        self.assertEqual(providers[1].executor_workflow,".github/workflows/samuel-native-github.yml")

    def test_branch_delete_is_skill_first_with_connector_fallback(self):
        providers=resolve_providers("GITHUB_BRANCH_DELETE")
        self.assertEqual([p.name for p in providers],["repository-native","github-connector"])
        self.assertEqual(providers[0].kind,"skill")
        self.assertEqual(providers[0].contract,"github-branch-delete")

    def test_repository_native_merge_provider_is_executable(self):
        result=validate_registry()
        self.assertEqual(result["status"],"PASS")
        self.assertIn("GITHUB_PR_MERGE:repository-native",result["checked"])
        self.assertIn("GITHUB_BRANCH_DELETE:repository-native",result["checked"])

    def test_unsupported_prose_cannot_remove_registered_provider(self):
        for claim in ("OpenAI safety check","merge authority missing","workflow_dispatch API missing","no fallback merge provider exists"):
            providers=resolve_providers("GITHUB_PR_MERGE")
            self.assertIn("repository-native",[p.name for p in providers],claim)

    def test_negative_branch_delete_verdict_requires_all_provider_failures(self):
        with self.assertRaisesRegex(
            CapabilityRegistryError,
            "negative capability verdict forbidden before registry exhaustion",
        ):
            assert_capability_exhausted(
                "GITHUB_BRANCH_DELETE",
                {"github-connector":"delete ref action is not exposed"},
            )

    def test_negative_branch_delete_verdict_allowed_only_after_registry_exhaustion(self):
        result=assert_capability_exhausted(
            "GITHUB_BRANCH_DELETE",
            {
                "repository-native":"lease-guarded branch-delete contract failed",
                "github-connector":"delete ref action is not exposed",
            },
        )
        self.assertEqual(result["status"],"CAPABILITY_EXHAUSTED")
        self.assertEqual(
            result["failed_providers"],
            ["repository-native","github-connector"],
        )

    def test_negative_verdict_rejects_unknown_or_empty_failure_evidence(self):
        with self.assertRaises(CapabilityRegistryError):
            assert_capability_exhausted(
                "GITHUB_BRANCH_DELETE",
                {
                    "repository-native":"failed",
                    "github-connector":"failed",
                    "imaginary-provider":"failed",
                },
            )
        with self.assertRaises(CapabilityRegistryError):
            assert_capability_exhausted(
                "GITHUB_BRANCH_DELETE",
                {
                    "repository-native":"failed",
                    "github-connector":"",
                },
            )

    def test_unbound_capability_fails_closed(self):
        with self.assertRaises(CapabilityRegistryError):
            resolve_providers("UNBOUND_CAPABILITY")

    def test_create_write_capabilities_are_explicitly_registered(self):
        expected = ("GITHUB_FILE_CREATE", "GITHUB_FILE_UPDATE", "GITHUB_BRANCH_CREATE")
        for capability in expected:
            with self.subTest(capability=capability):
                providers = resolve_providers(capability)
                self.assertEqual([p.name for p in providers], ["github-connector", "repository-native"])
                self.assertEqual(providers[1].workflow, ".github/workflows/samuel-repository-mutation.yml")
        self.assertEqual([p.name for p in resolve_providers("GITHUB_PR_CREATE")], ["github-connector"])

    def test_create_provider_route_is_validated_and_awaits_all_failures(self):
        validated = validate_registry()
        self.assertEqual(validated["status"], "PASS")
        for capability in ("GITHUB_FILE_CREATE", "GITHUB_FILE_UPDATE",
                           "GITHUB_BRANCH_CREATE", "GITHUB_PR_CREATE"):
            self.assertIn(capability + ":github-connector", validated["checked"])
        with self.assertRaisesRegex(CapabilityRegistryError, "unexhausted providers"):
            assert_capability_exhausted(
                "GITHUB_FILE_CREATE", {"github-connector": "temporary connector failure"}
            )

    def test_pr_create_connector_only_and_no_native_fallback(self):
        providers = resolve_providers("GITHUB_PR_CREATE")
        self.assertEqual([p.name for p in providers], ["github-connector"])
        self.assertEqual(providers[0].kind, "external")
        self.assertEqual(providers[0].priority, 10)
        checked = validate_registry()["checked"]
        self.assertIn("GITHUB_PR_CREATE:github-connector", checked)
        self.assertNotIn("GITHUB_PR_CREATE:repository-native", checked)

    def test_pr_create_negative_verdict_requires_connector_evidence(self):
        with self.assertRaisesRegex(CapabilityRegistryError, "unexhausted providers"):
            assert_capability_exhausted("GITHUB_PR_CREATE", {})
        result = assert_capability_exhausted(
            "GITHUB_PR_CREATE",
            {"github-connector": "verified provider-local unavailability"},
        )
        self.assertEqual(result["failed_providers"], ["github-connector"])
        with self.assertRaises(CapabilityRegistryError):
            assert_capability_exhausted(
                "GITHUB_PR_CREATE",
                {"repository-native": "not a registered PR-create provider"},
            )

    def test_native_repository_mutation_still_denies_registry_self_edit(self):
        from pathlib import Path
        import json
        policy=json.loads(Path("automation/samuel/repository-mutation-policy.json").read_text())
        self.assertIn("skills/capability-registry.json",
                      policy["mutation"]["file_paths"]["deny"])

if __name__=="__main__":
    unittest.main()
