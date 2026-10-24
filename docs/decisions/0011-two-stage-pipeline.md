# 0011. A two-stage pipeline: Haiku screens, Opus extracts flagged turns

Date: 2026-10-23 · Status: Accepted

## Context

Opus is the default model and Haiku runs the demo. Opus costs about forty times as much per output token. Most
turns of a real call are small talk, so a cheap model could screen them and pass only the turns that matter to the
expensive one. The comparison must show whether that keeps Opus's accuracy at a fraction of its cost, without
changing the API or breaking the import layering.

## Decision

- **Screen.** Haiku runs the unchanged v1 extraction on the whole transcript.
- **Flag.** Every turn Haiku labels as anything but NONE is flagged. The flag labels are a setting.
- **Extract.** Flagged turns, each with up to two preceding turns for context, are merged into contiguous windows.
  Each window goes to Opus as a sub-transcript with the same v1 prompt. Indices are remapped, spans on context-only
  turns are discarded, and the quote check runs against the original turns.
- **Merge.** Opus's spans replace Haiku's on flagged turns; Haiku's NONE spans stand elsewhere.
- **Placement.** An `Analyzer` protocol in `extractor/analyzer.py` (`analyze()` and `describe()`), which
  `Extractor` and a new `TwoStageExtractor` in `extractor/two_stage.py` both satisfy. `extractor/factory.py` builds
  any configuration: `haiku`, `sonnet`, `opus` or `two-stage`. The extractor imports nothing from `api` or
  `evaluation`.
- **Caching per stage.** The evaluation cache wraps each stage, so the screen stage shares keys with a Haiku run.
- **Reporting.** One run, one report: cost is the sum of both stages and latency is each item's wall clock. The
  report adds the escalation rate (flagged turns over all turns) and screen misses (expected ledger spans on
  unflagged turns).
- **API.** The API keeps the single-model extractor; `AnalyzeResponse` and `API_VERSION` don't change.

## Consequences

- **No new prompt.** Both stages use v1, so the comparison measures the pipeline, not a newly tuned prompt.
- **Screen misses are measured.** A commitment Haiku calls NONE never reaches Opus; the report counts these, which
  decides whether Haiku is a safe screen.
- **Small saving on eval data.** Eval items are built around labels, so nearly all have a flagged turn. The
  escalation rate, not the eval-set cost, predicts the saving on real calls.
- **More calls per item.** A transcript with separated flagged turns needs one Opus call per window.

## Alternatives considered

- **Escalate the whole item.** Simpler, but a real call almost always contains one commitment, so nearly every
  call would go to Opus and nothing would be saved.
- **A dedicated screening prompt.** Possibly cheaper per screen, but it is a second prompt to version and tune.
- **Flagged turns without context.** Smaller requests, but replies like "Sure, I'll do it" lose the request that
  makes them a commitment.
