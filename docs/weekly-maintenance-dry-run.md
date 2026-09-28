# Paul weekly-maintenance dry run

This runbook defines a reproducible Mon-Sun dry run for the weekly maintenance cycle.

## Evidence boundary

- Raw observations are append-only evidence.
- Collection does not modify skills or consumer pins.
- Derived summaries reference raw observation identities.
- Improvement work is performed only on a workload-owned branch and submitted as a pull request.
- Uncertain failures remain `UNKNOWN`; dependency attribution is recorded only when evidence supports it.

## Phases

| UTC weekday | Phase | Required result |
| --- | --- | --- |
| Monday-Friday | `collect` | Durable raw skill-activation and workflow-failure observations |
| Saturday | `analyze` | Deterministic summary and evidence-backed candidate list |
| Sunday | `improve` / `close` | Bounded branch/PR artifacts or an explicit no-change closure |

## Reproducibility procedure

1. Run collection for each weekday using the existing maintenance entry point.
2. Record the raw evidence location and stable deduplication identity for every observation.
3. Re-run Saturday analysis against the same raw evidence snapshot and verify identical derived output.
4. For each selected candidate, record the observed problem, evidence references, proposed delta, tests, consumer-parity checks, and rollback boundary.
5. Create or reuse a workload-owned branch for implementation; never mutate `main` directly.
6. Run validation and open a reviewable pull request. Do not auto-merge solely because the cycle produced a patch.
7. On Sunday closure, record merged improvements, proposed improvements, rejected candidates, known external failures, pending migrations, and next-week questions.

## Dry-run acceptance record

A completed dry run must retain:

- one raw evidence reference for each collection day;
- the Saturday input snapshot and derived summary;
- the Sunday branch and pull-request references, or a documented no-change decision;
- duplicate/retry decisions keyed by the stable run identity;
- failure categorization with external-dependency uncertainty preserved;
- the exact scheduler date and UTC phase selected.
