# governed-matrix

Portable build-once / fan-out / fan-in execution for independent governed experiment cases.

## Problem owned

A consumer should not hand-author GitHub matrix topology for each experiment. The central contract owns:

```text
plan
  -> governed prepare / build once
  -> tar shared bundle with file modes preserved
  -> independent case runners
  -> case evidence upload even on failure
  -> optional aggregate over downloaded case evidence
```

This is deliberately separate from `governed-work`:

- `governed-work` owns serial P0..Pn execution.
- `governed-matrix` owns parallel case topology and build artifact transfer.

## Mandatory routing rule

Experiment execution topology is selected from the manifest shape, never from an
issue number or sequence number.

```text
cases absent       -> governed-work serial execution
cases length >= 1  -> governed-matrix execution
cases = []         -> invalid manifest
```

When an experiment has one or more independent cases, the cases **must** be
declared in the matrix manifest and executed through `governed-matrix`.
A serial `governed-work` stage must not hide a multi-case sweep inside an
internal Python/shell loop.  Prepare/build work belongs in the prepare manifest;
independent cases fan out through matrix runners; cross-case interpretation
belongs in the optional aggregate step.

Consumer workflows must route from this manifest classification. They must not
hard-code matrix eligibility by issue number, sequence number, case name, or
historical allowlist.

## Consumer contract

The consumer checks in one matrix manifest plus one ordinary prepare manifest.

Example:

```json
{
  "schema_version": 1,
  "issue": 253,
  "sequence": 7,
  "title": "fixed-T chi sweep",
  "prepare_manifest": "automation/manifests/experiments/Issue_253_experiments07_prep.json",
  "bundle_paths": [
    "physics_app/physics-opt",
    "experiments/Issue253_g1_gummel_dt_release/generated_parallel"
  ],
  "max_parallel": 4,
  "cases": [
    {
      "id": "ref_chi0p1",
      "name": "chi=0.1",
      "command": ["python3", "experiments/.../parallel_control.py", "--case", "ref_chi0p1"],
      "timeout_seconds": 1800,
      "artifacts": ["experiments/.../results_parallel/ref_chi0p1_*"]
    }
  ],
  "aggregate": {
    "name": "aggregate",
    "command": ["python3", "experiments/.../parallel_control.py", "--aggregate"],
    "timeout_seconds": 300,
    "artifacts": ["experiments/.../results_parallel/parallel_summary.json"]
  }
}
```

The optional aggregate command receives:

```text
CHATGPT_MATRIX_EVIDENCE_ROOT=<downloaded case-evidence directory>
```

## Reusable workflow

Consumers call the central workflow pinned to the same exact immutable central SHA supplied as `operation_sha`:

```yaml
jobs:
  matrix:
    uses: HyungseonSong-plasma/chatgpt-operation/.github/workflows/governed-matrix.yml@<exact-sha>
    with:
      issue: "253"
      sequence: "07"
      manifest: automation/manifests/experiments/Issue_253_experiments07_matrix.json
      base_sha: <exact-consumer-sha>
      operation_sha: <same-exact-sha>
```

## Python entrypoint preflight

When a prepare, case, or aggregate command launches a repository Python file directly (for example `python3 path/to/control.py`), trigger `PYTHON_ENTRYPOINT` and apply the `python-entrypoint-preflight` skill before execution. Repository-local imports must have an explicit import contract; current working directory is not sufficient evidence.

A repository-local `ModuleNotFoundError` in prepare is a harness/infrastructure failure. It does not classify the scientific case. Repair the entrypoint/launcher, preserve scientific inputs, and relaunch at a new exact consumer head.

## Safety / reproducibility rules

- Each matrix case uses an independent GitHub runner.
- `fail-fast` is false.
- Matrix width is manifest-bounded to 1..8 concurrent lanes.
- Bundle paths are exact repository-relative files/directories, not globs.
- An explicitly listed top-level symlink file is allowed only when it resolves to a regular file inside the workspace; it is dereferenced into the tar as a regular file. Recursive directory symlinks remain forbidden.
- Bundle paths may not overlap and links are rejected.
- Shared bundles are tar archives, preserving executable mode without host-side chmod of root-owned build outputs.
- Ephemeral cache directories (`.git`, `.jitcache`, `__pycache__`, `.pytest_cache`) are excluded before recursion so root-owned runtime caches cannot block bundle creation.
- Every case is exact-`base_sha` bound.
- Every case writes deterministic evidence and its upload step uses `always()`.
- Aggregate runs after case completion even when a case fails, provided prepare succeeded.
- Scientific interpretation remains consumer-owned.


## External build-artifact staging

When prepare/build produces a runtime-critical file outside the consumer workspace, trigger `ARTIFACT_STAGING` and use the central `artifact-staging` skill before bundle creation.

The caller must establish the exact source path from current build/runtime evidence. Guessed paths, globbed copy commands, recursive discovery, and basename-only selection are not accepted staging contracts.

For nested Docker/runtime preparation, the reusable workflow exposes the exact operation checkout to the prepare process through:

```text
CHATGPT_OPERATION_ROOT
CHATGPT_OPERATION_SHA
```

Consumers may mount that exact checkout read-only into the nested runtime and invoke `chatgpt_operation.artifact_staging`. The staged repository-relative destination is then safe to declare in `bundle_paths`.
