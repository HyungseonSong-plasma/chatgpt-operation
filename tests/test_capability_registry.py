import unittest
from chatgpt_operation.skills.capability_registry import (
    CapabilityRegistryError, resolve_providers, validate_registry,
)

class CapabilityRegistryTests(unittest.TestCase):
    def test_merge_chain_is_authoritative_and_deterministic(self):
        providers=resolve_providers("GITHUB_PR_MERGE")
        self.assertEqual([p.name for p in providers],["github-connector","repository-native"])
        self.assertEqual(providers[1].workflow,".github/workflows/samuel-controller.yml")
        self.assertEqual(providers[1].executor_workflow,".github/workflows/samuel-native-github.yml")

    def test_repository_native_merge_provider_is_executable(self):
        result=validate_registry()
        self.assertEqual(result["status"],"PASS")
        self.assertIn("GITHUB_PR_MERGE:repository-native",result["checked"])

    def test_unsupported_prose_cannot_remove_registered_provider(self):
        for claim in ("OpenAI safety check","merge authority missing","workflow_dispatch API missing","no fallback merge provider exists"):
            providers=resolve_providers("GITHUB_PR_MERGE")
            self.assertIn("repository-native",[p.name for p in providers],claim)

    def test_unbound_capability_fails_closed(self):
        with self.assertRaises(CapabilityRegistryError):
            resolve_providers("UNBOUND_CAPABILITY")

if __name__=="__main__":
    unittest.main()
