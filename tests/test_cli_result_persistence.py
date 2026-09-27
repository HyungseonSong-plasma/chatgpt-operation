import json
from pathlib import Path
from tempfile import TemporaryDirectory

from chatgpt_operation.cli import persist


def test_cli_persist_writes_strict_json_with_real_trailing_newline():
    with TemporaryDirectory() as directory:
        path=Path(directory)/"result.json"
        payload={"status":"pass","nested":{"value":1}}
        persist(str(path),payload)
        raw=path.read_text(encoding="utf-8")
        assert raw.endswith("\n")
        assert not raw.endswith("\\n")
        assert json.loads(raw)==payload
