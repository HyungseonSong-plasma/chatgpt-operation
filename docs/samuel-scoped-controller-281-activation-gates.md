# Samuel scoped Controller #281 — technical activation and authority gates

**Status:** DRAFT / REVIEWABLE, not activated. This document is evidence and a
future release checklist, **not** authority to change workflow, ResearchState,
issue labels, schedules, secrets or repository security settings.

## Exact identities and current blockers (2026-11-09)

- Canonical OS main: `ae3feaea1eefc02337d9749a49868c867d3054cc`.
- Draft stack: #266 (`94fcd151`) → #273 (`f12e3ab1`) → #277.
- #255: **closed** and previously reconciled to `NO_MUTATION_NEEDED`
  because the exact requested branch was already absent. The global
  `<!-- samuel-controller-state -->` comment in closed Issue #44 still owns
  `issue:255`, revision 2, with its genuine escalated predispatch reasoning
  error; **do not remove or relabel that failure as a successful deletion**.
  Final reconciliation evidence:
  https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/255
- #256: **open**, `samuel` label, `admitted` in the global ledger. Its
  A/B Production Schema experiment classified a shared **HTTP 401 /
  invalid_api_key** provider failure, not a successful typed response.
  Evidence: https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42233434153
  and https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/256
- #281: **open without `samuel` label**, not admitted.
  https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/281
- Dedicated ChatGPT scheduled Controller: **disabled**, and must not
  dispatch before the required source-owned work admission and routing gates.

## Implemented Draft-only technical components

1. `scoped_work_gate.py`: complete open-Issue and durable Admission/state
   snapshot validation; mismatched owner, competing work and missing labels
   fail closed.
2. `scoped_wake_binding.py`: checked-in repo-owned candidate rather than
   scheduler-selected work ID; authenticated native run provenance
   validation; no authorization to dispatch.
3. `scoped_wake_native.py`: native GitHub REST **GET-only** reader for the
   canonical in-flight run, exact main SHA, pinned checked-in policy, two-pass
   complete open Issue inventory and two-pass global ledger comments. Valid
   candidate remains a `SCOPE_CANDIDATE` **preview**; changed snapshots and
   missing/forged credentials fail closed.
4. `python -m chatgpt_operation.controller.scoped_wake_native`: a
   read-only, GitHub-run-bound preflight entrypoint. It accepts no
   work-selection input. It requires the native runner environment and
   authenticated GET access; it cannot issue a GitHub write.
5. `automation/samuel/agent-child-scoped-preview-281.json` remains
   `mode=preview_only`, **`enabled=false`**. This cannot start work,
   even if externally triggered. CI simulation with `enabled=true` tests
   the candidate algorithm only; it is not production deployment.
6. `agent_issue_durable_executor.py`: one-step Child executor prototype
   persisting immutable Parent operation intents before CREATE, FINALIZE,
   native LINK, and parent RECORD. Stable read-after confirmation is
   required for advancement; ambiguous/unknown ACKs **block** without a
   second uncertain create. It is not callable from the deployed Bootstrap
   and lacks a production-bound exclusive writer lease. Offline tests
   include 20 serial Child allocations, 20 replays, lost ACK before/after
   remote creation and a simulated hard exit. Not a real SIGKILL or 20
   concurrent GitHub Actions acceptance test.

All Draft-only testing and readback are *separate* from proof of actual
20-Child, lost-ACK, process SIGKILL, and security isolation in GitHub Actions.

## Remaining independent gates before actual Controller work

| Gate | Owner / required exact evidence | Condition |
| --- | --- | --- |
| A. Closed #255 terminal ownership release | Samuel StateKernel with owner-approved, audit-preserving retirement/rollover. Existing failure remains recoverable; complete reread of #44 state and ledger | **BLOCKED** — current `can_rollover_state` rejects escalated failure |
| B. #256 diagnostic disposition | Human-accepted diagnostic classification / terminal Issue decision, no forged A/B provider success; current `samuel` Admission resolved via normal lifecycle | **BLOCKED** — open and admitted |
| C. Secure production bootstrap entrypoint | Separate, privileged, reviewable change to `.github/workflows/samuel-bootstrap.yml`, **before heartbeat or any other write**, with authenticated in-run exact-HEAD scope check and no external work selection, including replay/recursive dispatch paths | **BLOCKED** — workflow mutation denied by the ordinary repository-mutation policy; separate approval required |
| D. #281 Admission | Exact live work Parent and `samuel` label only **after** A/B/C are satisfied; stable ledger write through canonical admission owner | **BLOCKED** — no label and not admitted |
| E. Child writer | Intent-first API executor is Draft-implemented and mock-tested (20 Child replay, uncertain ACK blocking). Bind it to authenticated exclusive Bootstrap authority, qualify actual native linkage, real process SIGKILL, live 20-agent concurrency and provenance | **DRAFT COMPLETE / LIVE NOT PROVEN** |
| F. Promotion | Exact integrated HEAD tests, applicable protected branch rules, explicit merging and production activation approval | **BLOCKED** |

**Independent technical review:** explicitly waived for the bounded Draft
continuation by the user on 2026-11-09. Do **not** claim an independent review
occurred or that this waived security, protected-branch, merge, ownership,
credential or workflow-activation gates.

## Non-action rules

- No label on #281 until the production Bootstrap gate is approved and on
  main. Labelling #281 today would trigger unscoped existing workflow events.
- Do not clear, overwrite or fake the historical #255 error to free the
  single global state slot. Do not silently close #256 or equate a classified
  invalid API credential with successful reasoning.
- Do not invent a new per-task ResearchState owner or change the global #44
  authority without the separately required ResearchState migration approval.
- Do not bypass `.github/workflows/**` mutation policy via another provider.
  An explicit, owner-approved privileged change route is required.
- A CLI preview, even with all green CI checks, can never authorize actual
  dispatch. Live Bootstrap must independently revalidate before any write.

## Release decision

The **maximum safe state under the current Draft-only authority** is a
read-only, authenticated, exact-HEAD and fail-closed scoped preflight with
tests. A runnable #281 Controller needs the independent authority gates above;
turning on the disabled schedule or Issue label earlier is unsafe.
