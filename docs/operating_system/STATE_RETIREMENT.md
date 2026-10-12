# Durable State Retirement

Samuel owns one authoritative durable StateKernel slot. Repository closure by itself does not authorize overwriting that slot with another workload.

## Quiescent retirement

A closed workload may enter explicit retirement only when the current StateKernel has:

- no queued actions;
- no execution results;
- no diagnostic recovery in `open` or `needs_evidence` state; and
- no existing retirement record.

When those conditions hold and repository observation proves the owning Issue is no longer open, the controller writes one typed `StateRetirement` record into the same StateKernel and advances the state revision exactly once. The evidence records the source Issue number, workload mode, retirement reason, and the revision from which retirement was derived.

Repository closure is accepted as evidence only from a complete bounded open-Issue observation. Bootstrap records `open_issues_complete`. If a second 100-item page exists, absence from the first page is not treated as closure and the quiescent retirement path remains unavailable.

## Two-phase ownership transfer

Retirement and acquisition are separate controller cycles:

1. observe closed + quiescent ownership and durably persist the retirement revision;
2. reload that retirement evidence on a later cycle, then permit a different admitted workload to acquire the StateKernel slot.

The first cycle may mark the retiring admission entry `complete`, but it does not activate the next workload. This prevents repository observation and cross-workload state replacement from occurring as one unaudited transition.

## Compatibility and safety

StateKernel schema version 3 adds optional retirement evidence while the decoder continues to accept schema versions 1 and 2.

Existing terminal-history rollover semantics remain unchanged. A state with pending or dispatched work cannot use quiescent retirement. Ordinary suspended work also blocks this path; the pre-existing terminal rollover rule for governance-nonretryable suspended actions remains separate. An unresolved diagnostic recovery always blocks quiescent retirement.

Replay is deterministic: once a valid retirement revision is present, the same state is rollover-eligible but cannot be retired a second time. Cross-workload durable writes remain rejected until either existing terminal proof or explicit durable retirement proof authorizes release of the slot.
