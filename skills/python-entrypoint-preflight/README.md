# python-entrypoint-preflight

Portable fail-closed skill for Python entrypoints launched by governed work, GitHub Actions, containers, or direct script execution.

## Problem owned

Repository-local Python control scripts often import repository packages such as `experiments.*`. Running a file by path changes `sys.path[0]` to the script directory, so an entrypoint that works under `python -m ...` or an interactive repository-root shell can fail in CI with:

```text
ModuleNotFoundError: No module named '<repository package>'
```

This is an execution-contract defect, not a scientific/runtime result.

## Trigger

```text
PYTHON_ENTRYPOINT
```

Trigger this skill before launching or repairing any governed Python entrypoint whose command is executed as:

```text
python3 path/to/script.py ...
```

and which imports repository-local packages outside the script directory.

## Required preflight

Before launch, inspect the exact entrypoint and exact command.

Classify one of:

```text
MODULE_ENTRYPOINT
DIRECT_SCRIPT_SELF_BOOTSTRAPPED
DIRECT_SCRIPT_EXTERNAL_PYTHONPATH
BLOCKED_IMPORT_CONTRACT
```

### Preferred contract

When package structure supports it, execute from repository root as a module:

```bash
python3 -m package.subpackage.module ...
```

This is preferred because import resolution is explicit and does not depend on the script's filesystem directory.

### Direct-script contract

If the consumer must execute a file path, one of these must be explicit before repository-local imports occur.

Self-bootstrap:

```python
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[N]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
```

or execution-owned environment:

```bash
PYTHONPATH=/workspace python3 /workspace/path/to/script.py ...
```

Do not assume current working directory alone makes the repository importable.

## Fail-closed checks

For a direct-script command that imports repository-local modules:

1. resolve the repository root from durable repository structure;
2. verify the entrypoint establishes that root on `sys.path`, or the exact launcher exports an equivalent `PYTHONPATH`;
3. verify the import bootstrap occurs before repository-local imports;
4. run the cheapest available import-only/preflight command before expensive build/simulation work;
5. if none is true, classify `BLOCKED_IMPORT_CONTRACT` and repair the harness before launch.

Do not weaken scientific inputs, tolerances, convergence criteria, or runtime guards to repair an import-contract failure.

## Generated control scripts

When creating a new repository-local experiment/controller script, apply this template by default:

```python
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]  # consumer must verify depth
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments... import ...
```

The parent depth is consumer-owned and must be verified; never cargo-cult `parents[1]`.

If the launcher already guarantees `PYTHONPATH=<repo-root>`, prefer not to duplicate bootstrapping unless the same script is also intentionally supported as a direct standalone entrypoint.

## Governed-work / governed-matrix integration

Before P0/P1/P2 or a matrix prepare stage launches a new Python control entrypoint:

```text
manifest command
  -> python-entrypoint-preflight
  -> import contract PASS
  -> governed-work / governed-matrix
```

A `ModuleNotFoundError` for a repository-local package during prepare is classified as:

```text
INFRASTRUCTURE_HARNESS_FAILURE
scientific_classification = UNRESOLVED
```

Repair only the harness/entrypoint and relaunch at a new exact consumer head.

## Retry invariant

After repair:

- preserve scientific case definitions and frozen physics;
- create a new exact consumer SHA;
- correlate only runs from that exact SHA;
- do not reinterpret the failed prepare attempt as scientific evidence.
