from pathlib import Path


def test_cli_has_no_direct_native_executor_call():
    source=Path("src/chatgpt_operation/cli.py").read_text()
    assert "execute_native_github(" not in source
    assert "ExecutionKernel(" in source
    assert 'native_runtime_provider("repository-native", transport)' in source
