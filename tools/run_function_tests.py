"""Run dependency-free module-level test functions that unittest does not discover."""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import traceback

sys.path.insert(0, str(Path.cwd()))


def load_module(path: Path):
    name = "_samuel_function_test_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    failures: list[str] = []
    unsupported: list[str] = []
    executed = 0
    for path in sorted(Path("tests").glob("test_*.py")):
        try:
            module = load_module(path)
        except Exception:
            failures.append(f"{path}: import failed\n{traceback.format_exc()}")
            continue
        for name, candidate in sorted(vars(module).items()):
            if not name.startswith("test_") or not inspect.isfunction(candidate):
                continue
            if candidate.__module__ != module.__name__:
                continue
            signature = inspect.signature(candidate)
            parameters = tuple(signature.parameters)
            if parameters not in {(), ("tmp_path",)}:
                unsupported.append(f"{path}:{name}{signature}")
                continue
            executed += 1
            try:
                if parameters == ("tmp_path",):
                    with TemporaryDirectory() as directory:
                        candidate(Path(directory))
                else:
                    candidate()
            except Exception:
                failures.append(f"{path}:{name}\n{traceback.format_exc()}")
            else:
                print(f"FUNCTION_TEST=PASS {path}:{name}")
    if unsupported:
        failures.append(
            "function tests with unsupported fixture parameters:\n" + "\n".join(unsupported)
        )
    if failures:
        raise SystemExit("\n\n".join(failures))
    print(f"FUNCTION_TESTS=PASS executed={executed}")


if __name__ == "__main__":
    main()
