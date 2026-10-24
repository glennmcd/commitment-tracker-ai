# 0012. A report-required regression gate that spends nothing in CI

Date: 2026-10-23 · Status: Accepted

## Context

A prompt, model or test-set change can lower accuracy, and CI should catch that before merge. Running the model
in CI would need an Anthropic key in the repository's secrets and would spend money on every change. Committed
reports already hold the results of local runs.

## Decision

- **Baseline.** `backend/eval/baseline.json` holds, per gated set and per gated configuration, the accepted ledger
  F1, field accuracy and failed-item count, with the model, effort, prompt version, prompt hash, set hash and
  source report. Updating it is a deliberate commit.
- **Gated configurations.** The default model (Opus, from the `Settings` field default) and the deployed demo
  model (Haiku, `DEFAULT_DEMO_MODEL` in `infra/lib/api-stack.ts`). A test checks that the baseline covers the demo
  model named in the stack.
- **`uv run eval-gate`.** A pure comparison of committed files. For each gated set and configuration it fails when:
  - no committed report matches the current prompt hash, model, effort and set hash (the report-required check);
  - the set hash differs from the baseline's;
  - ledger F1 dropped by more than 0.02 (exactly 0.02 passes, compared after rounding to six places);
  - any item failed;
  - re-scoring the report's stored predictions with the current metrics code gives different scores.
  Field-accuracy changes print as warnings.
- **Stored predictions.** Reports keep each item's predicted spans, so they can be re-scored offline.
  `uv run eval rescore` rewrites reports from them.
- **`uv run eval --offline`.** Reads only the response cache, fails on a miss and never reads an API key.
- **CI.** An `eval-gate` job with no secrets runs on every push. Its first step checks whether prompts, settings,
  extractor or evaluation code, `eval/sets/`, `eval/reports/` or `eval/baseline.json` changed, and exits
  successfully if not.
- **Live job, stubbed.** An `eval-live` job, `workflow_dispatch` only and `if: false`, with its steps written out
  and a note on what enabling it needs: a key in a protected environment, a spend cap, cache restore and the cost
  estimate.

## Consequences

- **CI never spends money.** It verifies that someone ran the evaluation and committed the result.
- **Changes wait for a local run.** A prompt or test-set change can't merge until its reports for Opus and Haiku
  are committed: roughly $1–2.75 per prompt version on `test`.
- **The demo is protected.** A prompt change that helps Opus but hurts Haiku fails the gate.
- **Metric changes are caught.** Changing the scoring code without rescoring the reports fails the gate.
- **Trust.** The gate trusts committed reports; a hand-edited report would pass. Reports are generated files and
  review should treat edits to them as suspicious.

## Alternatives considered

- **Run the evaluation in CI.** Real verification, but needs a key in CI and spends on every push.
- **Replay a committed response cache in CI.** Needs no key, but commits thousands of model responses and still
  can't verify a changed prompt, whose cache keys are new.
- **Gate only the default model.** Simpler, but the demo runs Haiku, and visitors would see regressions the gate
  missed.
- **A workflow-level `paths:` filter.** Native, but a required check stays pending when the workflow doesn't run.
