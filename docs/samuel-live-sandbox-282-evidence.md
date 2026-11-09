# Samuel Agent Child — isolated real GitHub sandbox #282

**Qualification:** PARTIAL LIVE PASS / FULL NATIVE-WRITER QUALIFICATION BLOCKED

**Date:** 2026-11-09. Repository:
`HyungseonSong-plasma/chatgpt-operation`.

This evidence is isolated from Samuel's active work queue. The sandbox was
created by explicit user instruction in this interactive session, not by
the disabled scheduled Samuel Controller. It does **not** grant the external
scheduler a new create, work-selection, or repository-mutation capability.

## Observed native GitHub identities

| Resource | Issue | Internal `id` | Status | Labels |
| --- | --- | ---: | --- | --- |
| New qualification Parent | [#282](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/282) | 6289580624 | OPEN | none |
| Child Alpha | [#283](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/283) | 6289591915 | OPEN | none |
| Child Beta | [#284](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/284) | 6289592486 | OPEN | none |

Each issue was created by a real GitHub Issue API write and subsequently
read independently through the GitHub REST Issue endpoint. No existing
sandbox #278–#280 was used. No issue was given the `samuel` label and
none is admitted as Samuel work.

Independent per-Child append-only Issue comments:
- [Alpha comment 6744632172](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/283#issuecomment-6744632172), created/updated both `2026-11-09T15:58:18Z`.
- [Beta comment 6744633635](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/284#issuecomment-6744633635), created/updated both `2026-11-09T15:58:21Z`.
- Each marker appears once on its own Child; neither Child received
  the other Child's receipt. The credential used for these direct
  human-directed sandbox posts is not a Bootstrap/agent security attestation.

The actual native `GET /issues/282/sub_issues` returned **[]**.
A native Sub-issue link was neither executed nor claimed. A standalone
[Parent audit](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/282#issuecomment-6744727500)
records the observed facts and outstanding gaps.

## Actual POSIX process SIGKILL in hosted GitHub Actions

The added `tests/test_agent_issue_sigkill_hosted.py` runs a fresh
subprocess against a **locally persisted, atomic fake GitHub REST store**;
the test sends a real OS `SIGKILL` after an intent record or a Child
creation has been committed.

- Killed after an intent: reloaded durable store has intent but no Child;
  replay reports `BLOCKED_UNCERTAIN_ACK` and performs zero Child POSTs.
- Killed after a committed Child POST: reloaded store contains one Child;
  replay observes the existing issue, completes FINALIZE/LINK/RECORD,
  and never repeats CREATE.
- Both cases completed successfully in GitHub Actions
  [run 42650485817](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42650485817)
  at exact source SHA
  `e9a6cfa4348d36c2a60534253829d86c8f9a5d5d`.
  The complete test suite was **1,028/1,028 PASS**.

The actual `SIGKILL` is proven for a local child process running
in hosted CI, **not** for a production Samuel process after a
real remote GitHub POST. That remains a separate integration gate.

## Missing live integration acceptance

| Required proof | Current verdict |
| --- | --- |
| GitHub Issue REST create/readback and two isolated per-Child comments | PASS — #282–#284 |
| Native Sub-issue attach and reverse parent readback for sandbox #282 | BLOCKED — no current approved live runner |
| Ambiguous remote Child CREATE ACK followed by authenticated remote readback | NOT PROVEN (only simulated/local) |
| Actual SIGKILL across an in-flight real GitHub REST Child POST | NOT PROVEN (hosted kill + local fake) |
| 20 real Child allocations/receipts, concurrency and duplicate constraints | NOT PROVEN (mock-tested only) |
| Exact-source-run ZIP/CDN token isolation, artifact digest and receipt provenance | NOT PROVEN live |
| Production Bootstrap/StateKernel migration, exclusive writer, #281 Admission | NOT AUTHORIZED |

The previously successful, real two-link native Sub-issue qualification
[run 42622488643](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42622488643)
and its successful replay
[run 42622654426](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42622654426)
are separate evidence limited to **closed sandbox #278–#280**.
The earlier one-shot
`.github/workflows/samuel-native-subissue-live-qualification.yml`
was intentionally deleted at commit
`a78bc11ba64b86486ad72807759f3bff317994fb`; it is absent
from current `main`, and its hardcoded old sandbox identities
must not be reused.

## Next gated action

A separately authorized privileged workflow change must introduce a
new **isolated** GitHub Actions live qualification runner (or another
approved provider with equivalent exact-scope credentials). It must
pin: repository, event, branch, SHA, allowed Parent #282, the
fresh Child internal IDs, exclusive concurrency group, allowed
REST endpoint/method list, permissions and audit artifacts. For
20-Child throughput, create a new bounded issue allocation set
only after the runner is authorized; do not pre-create 20 idle Issues.

The ordinary Samuel repository mutation policy explicitly excludes
`.github/workflows/**`; do **not** bypass that hard deny with
another Git provider, a revived archived workflow, or a changed branch.
No workflow file was changed or activated here.

No #44 authoritative State/PARENT change, no #255 escalation clearance,
no #256 Admission retirement, no #281 label, no PR merge, no scheduler
resumption, and no credential/ruleset change occurred in this test.
