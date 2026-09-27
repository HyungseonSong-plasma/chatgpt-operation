from pathlib import Path


def test_cli_has_no_direct_native_executor_call():
    source=Path("src/chatgpt_operation/cli.py").read_text()
    assert "execute_native_github(" not in source
    assert "ExecutionKernel(" in source
    assert 'native_runtime_provider("repository-native", transport)' in source


def test_native_kernel_failure_is_retryable_for_bounded_recovery():
    source=Path("src/chatgpt_operation/cli.py").read_text()
    marker='observation="native execution kernel failed closed"'
    start=source.index(marker)
    block=source[start:start+240]
    assert "retryable=True" in block
