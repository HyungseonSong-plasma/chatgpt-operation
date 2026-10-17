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

if __name__=="__main__":
    unittest.main()
