import unittest

from chatgpt_operation.controller.host_boundary import (
    HostBoundaryError, scheduled_controller_contract, validate_host_operation,
)


class HostBoundaryTests(unittest.TestCase):
    def test_only_canonical_bootstrap_dispatch_is_allowed(self):
        validate_host_operation(operation="dispatch_workflow",workflow="samuel-bootstrap.yml",ref="main")

    def test_direct_repository_write_is_forbidden(self):
        with self.assertRaises(HostBoundaryError):
            validate_host_operation(operation="merge_pr")

    def test_alternate_workflow_is_forbidden(self):
        with self.assertRaises(HostBoundaryError):
            validate_host_operation(operation="dispatch_workflow",workflow="samuel-native-github.yml",ref="main")

    def test_contract_names_external_role_as_trigger_only(self):
        c=scheduled_controller_contract()
        self.assertEqual(c["role"],"bootstrap_trigger_only")
        self.assertIn("repository_write",c["forbidden"])


if __name__=="__main__":
    unittest.main()
