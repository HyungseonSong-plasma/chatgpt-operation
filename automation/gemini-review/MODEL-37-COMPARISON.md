# Gemini 3.7 Flash comparison — owner-owned Workflow adoption

**Scope:** One-model availability comparison after owner-authorized Gemini 3.8 Flash
smoke failure on issue #314. This package is `PROPOSED_ONLY`, not a deployed
model change or an approved API call.

## Evidence

- Gemini 3.7 Flash is listed as a **Stable** model at:
  https://ai.google.dev/gemini-api/docs/models
  (model ID: `gemini-3.7-flash`, Structured Output supported).
- [Issue #314](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/314)
  invoked 3.8 Flash exactly once, and
  [run #43330926281](https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/43330926281)
  returned `API_HTTP_503`, not a verified model review.
- Google says HTTP 503 is temporary overload unrelated to quota, and
  recommends bounded backoff/retry:
  https://discuss.ai.google.dev/t/handling-429-503-errors-from-the-gemini-api/124640

## Reviewable model-only change

The reference file
`automation/gemini-review/model-37-comparison.proposed.yml`
has **exactly one replacement** from the installed Workflow as of central
main commit `7241b9ef630894d9ea769912751c2dd8184e7d10`:

```diff
-            --model gemini-3.8-flash \
+            --model gemini-3.7-flash \
```

No other Workflow keys, secret scopes, permissions, checkout pins, ingress,
source allowlist, timeout, output cap, concurrency, and receipt policy change.
The canonical 3.8 proposal is retained as a previous-variant reference. Tests
accept only either complete reviewed Workflow body, not arbitrary model IDs.

## Mandatory human-only adoption (protected path)

`automation/samuel/repository-mutation-policy.json` denies
`.github/workflows/**`. The owner must perform the protected file change
via their own GitHub web UI or authenticated local CLI, in a dedicated
reviewed PR; neither ChatGPT nor Samuel is authorized to write the Workflow.

1. Merge the *nonprivileged* preparation PR for this file and updated tests,
   after its CI passes.
2. In the repository, create a fresh branch from current `main`:
   `samuel/gemini-37-human-compare-314`.
3. Visit
   `https://github.com/HyungseonSong-plasma/chatgpt-operation/blob/samuel/gemini-37-human-compare-314/.github/workflows/samuel-gemini-review.yml`.
4. Click **Edit this file**. Replace the **single** exact line:
   `--model gemini-3.8-flash` → `--model gemini-3.7-flash`.
   Keep all other bytes and all other files unchanged.
5. Commit on that branch. Create a Draft PR into `main`.
6. Confirm exactly one changed path:
   `.github/workflows/samuel-gemini-review.yml`.
   Verify PR HEAD / required `test` and CI PASS. Review and merge
   only through ordinary owner-controlled protected PR governance.
7. Verify on `main` that the installed Workflow model is now
   `gemini-3.7-flash`, and that the registry remains unchanged.

**Do not** modify the repository mutation policy, rename the blocked path,
force-push `main`, or use the GitHub connector as a protected-file editor.

## One-shot comparison (after deployed model switch)

- Create a **new**, owner-authored `[Gemini Review]` Issue with the exact
  current codeQA PR #300 base/head/diff/hash/changed paths. Issue #312 or
  #314 cannot be replayed.
- Applying `samuel/gemini-review-approved` costs one possibly billable
  Google call; it must occur only on a new Issue with explicit user approval.
  Do not include credentials in the Issue, PR or logs.
- Source PR content and review criteria should remain identical across
  the model comparison (recheck exact current SHA before issuing).
- Compare `GEMINI_REVIEW=REVIEW_RETURNED` vs sanitized `API_HTTP_503`
  or other `UNKNOWN`. A successful 3.7 response suggests availability
  differences; it does not prove why the earlier 3.8 call failed.
- Model `PASS` is an independent review observation, **never** merge
  authorization or proof of codeQA domain semantic compatibility.
- This experiment deliberately leaves the prior single-request 90-second
  timeout and 2,048 output-token limit unchanged. Its per-call time/token
  constraints do **not** constitute a guaranteed financial spending cap.

## Rollback

If 3.7 is unsuitable, the owner opens another reviewed protected-file PR to
restore the **single model line** to `gemini-3.8-flash`. Preserve the
comparison evidence; never delete or relabel historical Issues to reset
one-shot limits.
