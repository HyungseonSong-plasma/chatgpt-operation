import unittest

from tools.validate_python_surfaces import (
    embedded_python_blocks,
    validate_workflow_text,
    workflow_run_scripts,
)


class ValidatePythonSurfacesTests(unittest.TestCase):
    def test_nested_shell_indentation_does_not_become_python_indentation(self):
        text = """
jobs:
  test:
    steps:
      - name: Example
        run: |
          if true; then
            python3 - <<'PY'
          import json
          value = {"ok": True}
          PY
          fi
"""
        scripts = workflow_run_scripts(text)
        self.assertEqual(len(scripts), 1)
        blocks = embedded_python_blocks(scripts[0])
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].startswith("import json"))
        self.assertEqual(validate_workflow_text(text, filename="example.yml"), [])

    def test_invalid_embedded_python_is_reported(self):
        text = """
jobs:
  test:
    steps:
      - run: |
          python3 - <<'PY'
          if True
              pass
          PY
"""
        failures = validate_workflow_text(text, filename="bad.yml")
        self.assertEqual(len(failures), 1)
        self.assertIn("bad.yml", failures[0])

    def test_unterminated_python_heredoc_is_reported(self):
        text = """
jobs:
  test:
    steps:
      - run: |
          python3 - <<'PY'
          print("x")
"""
        failures = validate_workflow_text(text, filename="unterminated.yml")
        self.assertEqual(
            failures,
            ["unterminated.yml:run-1: unterminated python3 heredoc"],
        )


if __name__ == "__main__":
    unittest.main()
