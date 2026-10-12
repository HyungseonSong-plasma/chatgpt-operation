from pathlib import Path

path = Path("tests/test_controller_runtime.py")
text = path.read_text(encoding="utf-8")

old1 = '''        with self.assertRaisesRegex(\n            ReasoningNodeError,\n            "not qualified for semantic planning: comment_issue",\n        ):\n            controller(ReasoningProviderRegistry(provider)).run_cycle(\n                trigger(),\n                comments=[admitted_comment()],\n                pending=[],\n                repository_context={\n                    "repository":"HyungseonSong-plasma/chatgpt-operation",\n                    "open_issues":[{"number":44}],\n                },\n            )\n        self.assertEqual(provider.calls,2)\n'''
new1 = '''        result=controller(ReasoningProviderRegistry(provider)).run_cycle(\n            trigger(),\n            comments=[admitted_comment()],\n            pending=[],\n            repository_context={\n                "repository":"HyungseonSong-plasma/chatgpt-operation",\n                "open_issues":[{"number":44}],\n            },\n        )\n        self.assertEqual(result.selected_work["kind"],"controller_recovery")\n        self.assertIsNone(result.execution_command)\n        self.assertIsNotNone(result.state_write)\n        recovered=decode_state(result.state_write["body"])\n        failure=next(iter(recovered.predispatch_failures.values()))\n        self.assertEqual(failure["failure_class"],"reasoning_validation")\n        self.assertEqual(failure["status"],"retryable")\n        self.assertIn(\n            "not qualified for semantic planning: comment_issue",\n            failure["last_error"],\n        )\n        self.assertEqual(provider.calls,2)\n'''

old2 = '''        with self.assertRaisesRegex(\n            ReasoningNodeError,\n            "not qualified for semantic planning: dispatch_workflow",\n        ):\n            controller(ReasoningProviderRegistry(provider)).run_cycle(\n                trigger(),\n                comments=[admitted_comment()],\n                pending=[],\n                repository_context={\n                    "repository":"HyungseonSong-plasma/chatgpt-operation",\n                    "open_issues":[{"number":44}],\n                },\n            )\n        self.assertEqual(provider.calls,2)\n'''
new2 = '''        result=controller(ReasoningProviderRegistry(provider)).run_cycle(\n            trigger(),\n            comments=[admitted_comment()],\n            pending=[],\n            repository_context={\n                "repository":"HyungseonSong-plasma/chatgpt-operation",\n                "open_issues":[{"number":44}],\n            },\n        )\n        self.assertEqual(result.selected_work["kind"],"controller_recovery")\n        self.assertIsNone(result.execution_command)\n        self.assertIsNotNone(result.state_write)\n        recovered=decode_state(result.state_write["body"])\n        failure=next(iter(recovered.predispatch_failures.values()))\n        self.assertEqual(failure["failure_class"],"reasoning_validation")\n        self.assertEqual(failure["status"],"retryable")\n        self.assertIn(\n            "not qualified for semantic planning: dispatch_workflow",\n            failure["last_error"],\n        )\n        self.assertEqual(provider.calls,2)\n'''

for old, new in ((old1, new1), (old2, new2)):
    if text.count(old) != 1:
        raise SystemExit(f"expected one legacy assertion block, found {text.count(old)}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("ISSUE_211_LEGACY_TEST_PATCH=PASS")
