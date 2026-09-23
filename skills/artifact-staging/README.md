# artifact-staging

Portable deterministic staging of build/runtime artifacts from one exact source path to one exact consumer-workspace destination.

## Contract

Before authoring a staging specification, the caller must identify the artifact, its producer, one exact source path, one exact destination, current evidence establishing that source location, and the expected object type.

If the exact source location is not established, the affected path is ARTIFACT_LOCATION_UNRESOLVED and staging is forbidden. Do not substitute a conventional or likely path.

The v1 implementation rejects wildcard selectors, parent traversal, missing sources, source-type mismatches, destination conflicts, SHA mismatches, and implicit symlink following. Symlinks are copied only when symlink_policy is explicitly materialize.

Each entry requires: id, source, destination, producer, and location_evidence. destination must be workspace-relative. source may be absolute or workspace-relative. expected_sha256 is optional.

Execution:

    PYTHONPATH=/chatgpt-operation/src python3 -m chatgpt_operation.artifact_staging stage \
      --spec /workspace/path/to/artifact-staging.json \
      --workspace /workspace \
      --evidence /workspace/path/to/staging-evidence.json

Self-test:

    PYTHONPATH=src python3 -m chatgpt_operation.artifact_staging self-test

Evidence records the declared source, resolved source, destination, producer, location evidence, materialization state, SHA256, mode, size and whether the copy was needed.

Copy completion is artifact-transfer evidence only. Runtime loading, ABI compatibility, numerical correctness and scientific validity require their own consumer-owned evidence.

## Governed-matrix composition

When prepare/build creates a runtime artifact outside the consumer workspace, invoke this skill inside the same build/runtime environment before that environment is destroyed, then include the staged destination in governed-matrix bundle_paths.

A consumer wrapper launching Docker or another nested runtime should mount the exact pinned chatgpt-operation checkout read-only and invoke this module there. Hand-authored wildcard cp/find staging is not equivalent.
