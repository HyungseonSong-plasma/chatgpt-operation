# state-refresh

Portable deterministic planning for delta-based controller fresh reads.

## Problem owned

A controller needs current truth before acting, but it should not reconstruct the
entire repository state on every invocation. This skill computes the smallest
safe read set from a durable checkpoint, cheap fingerprints, immutable pins, and
the next planned mutation.

It does **not** fetch GitHub state itself. The caller maps repository-specific
queries onto generic read keys and executes the returned plan.

## State machine

```text
durable checkpoint
      |
      v
cheap fingerprint probes
      |
      +-- checkpoint/rules/scope invalid --> FULL_REFRESH_REQUIRED
      |
      +-- probe missing -----------------> PROBE_REQUIRED
      |
      +-- probe failure -----------------> PROBE_BLOCKED
      |
      +-- fingerprint changed -----------> DELTA_REFRESH
      |
      +-- unchanged + mutation ----------> PREWRITE_ONLY
      |
      `-- unchanged/read-only -----------> CHECKPOINT_CURRENT
```

The invariant is:

```text
fresh-read scope may shrink
authoritative mutation-time read may not
```

## Surface model

Each surface declares:

- `MUTABLE` or `PINNED_IMMUTABLE`;
- `FLOATING` or `EXACT` locator identity;
- whether it is decision-critical for this controller cycle;
- checkpoint and current fingerprints;
- cheap `probe_reads`;
- expensive `detail_reads`;
- authoritative `prewrite_reads`.

A verified `PINNED_IMMUTABLE` surface must use an `EXACT` locator and is
skipped on later cycles. A floating ref such as `main`, `latest`, an open PR,
or a branch head must never be classified as pinned immutable.

## Full refresh triggers

The evaluator requires a full consumer-defined bootstrap when any of these are
true:

- no durable checkpoint exists;
- checkpoint trust is lost;
- controller phase changes;
- canonical rule revision changes;
- controller scope changes;
- current evidence contradicts the checkpoint;
- the next action cannot be established from the checkpoint.

The central skill intentionally does not prescribe the repository-specific full
bootstrap read set.

## Delta refresh

For a decision-critical mutable surface:

1. if it has not been probed, return only its cheap `probe_reads`;
2. compare the current fingerprint with the checkpoint fingerprint;
3. if unchanged, skip its detail reads;
4. if changed, return only that surface's `detail_reads`;
5. if the probe failed, block rather than silently using stale state.

Non-critical surfaces that are not mutation targets do not force a probe.

## Mutation-time safety

Every planned mutation target must be a `MUTABLE` surface and must declare
non-empty `prewrite_reads`.

Even when all fingerprints are unchanged:

```text
planned mutation
  -> PREWRITE_ONLY
  -> authoritative target read
  -> mutation
```

This preserves repository mutation/fresh-read safety while removing unrelated
reads.

Pinned immutable surfaces cannot be mutation targets.

## Typical GitHub mapping

A consumer may map generic read keys like:

```text
main.identity       -> current main SHA
pr.identity         -> PR updated_at + head/base SHA
issue.identity      -> issue updated_at/state
ci.head_summary     -> exact-head run existence/status

pr.reviews          -> review threads/submissions
issue.comments      -> latest relevant comments
ci.exact_head       -> jobs/check details

branch.authoritative -> branch HEAD immediately before ref mutation
file.authoritative   -> target file content/blob SHA immediately before update
pr.authoritative     -> PR head/base/mergeability/gates immediately before merge
```

The code remains tool-agnostic; these names are caller-owned strings.

## CLI

```bash
PYTHONPATH=src python3 -m chatgpt_operation.cli controller state-refresh \
  --input state-refresh.json

PYTHONPATH=src python3 -m chatgpt_operation.cli controller state-refresh-self-test
```

The intended composition is:

```text
state-refresh
  -> minimal current evidence

controller-throughput
  -> useful work scheduling

controller-lifecycle
  -> completion / disable safety

repository-mutation
  -> authoritative write safety
```
