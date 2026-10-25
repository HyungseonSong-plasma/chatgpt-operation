import unittest
from chatgpt_operation.controller.native_repository_boundary import (
    NativeRepositoryBoundaryError, require_native_repository_scope,
)


class NativeRepositoryBoundaryTests(unittest.TestCase):
    def test_same_repo_allowed(self):
        require_native_repository_scope("org/controller", "org/controller")

    def test_cross_repo_denied(self):
        with self.assertRaisesRegex(NativeRepositoryBoundaryError, "cross-repository"):
            require_native_repository_scope("org/codeQA", "org/controller")

    def test_no_verified_origin_denied(self):
        for origin in (None, ""):
            with self.subTest(origin=origin), self.assertRaises(NativeRepositoryBoundaryError):
                require_native_repository_scope("org/controller", origin)
