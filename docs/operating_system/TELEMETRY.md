# Skill activation telemetry

This subsystem records **observed Paul skill utilization**. It is non-authoritative: it is not project state, scientific evidence, mutation authority, acceptance/routing truth, or a quality/compliance score. Normal Paul initialization MUST NOT load telemetry or telemetry history.

## Event sources

Two sources use the same event contract in `schemas/skill-activation.schema.json`.

1. **GitHub-executed activation.** A consumer workflow or central executable emits one event immediately when it actually invokes/loads a skill. Use `source=github_execution`. `activation_id` should be derived from the logical execution identity (for example run id + logical operation + skill), excluding retry/run-attempt identity so safe reruns deduplicate.
2. **Interactive ChatGPT activation.** Where no native activation hook exists, the operating path may make a small explicit, out-of-band emission after a skill is actually loaded. Use `source=interactive_explicit`. The emission is best-effort and MUST NOT alter or delay the semantic result of the skill. Availability/catalog discovery is not an activation.

Every event preserves consumer repository, exact 40-hex central revision, skill name, skill path identity, trigger, and UTC-capable timestamp. Producers SHOULD supply `activation_id`; when absent the deterministic fallback identity includes the timestamp and therefore only protects exact replay.

## Collection and aggregation

Raw records are append-only JSONL (or an equivalent immutable GitHub artifact/event record). Aggregation is a pure deterministic operation: validate, derive a stable event identity, deduplicate, sort, then count. A retry carrying the same `activation_id` cannot increment the count twice even if its observation timestamp changes.

Required derived views are activations by skill/day, skill/consumer, trigger, total/week, and skills with zero observed activation. Zero observed activation means only that no event was observed.

## Retention and compaction

Raw events are retained for the active weekly analysis window plus a short retry/audit buffer. After a weekly aggregate is sealed, raw records older than 35 days MAY be deleted if the aggregate and its input revision/window metadata are retained. Daily aggregates MAY be compacted into weekly aggregates after 90 days. Retention is operational housekeeping only and never changes Paul decisions.

Repository commits are not the preferred event store because one commit per activation creates unbounded repository-write noise. GitHub-native artifacts/events or periodically batched append-only records are preferred.

## Isolation invariant

`session-bootstrap` and `state-refresh` remain the normal INIT path. They do not read telemetry, aggregates, or this document during initialization. Telemetry may be inspected only by an explicitly activated telemetry/maintenance flow.
