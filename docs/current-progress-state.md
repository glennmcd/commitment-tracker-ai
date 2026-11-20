# Current progress: evaluation

As of 2026-10-26 (v0.10.0), measured against the Evaluation plan in [spec.md](spec.md).

The machinery is built: blind review, the regression gate, the reports and the comparison runs. What's left is
mostly data. Dev has 34 of its 50 items, test has 68 of 150, and none of the 30 audio clips exist yet.

| Spec item | Target | Where it stands |
| --- | --- | --- |
| Dev set | 50 items | **34** (24 spec + 10 hand-written) |
| Held-out test set | 150 items | **68**, all model-drafted and blind-reviewed: Gemini 25, ChatGPT 22 + 21 |
| Hand-written test items | 30 in the plan | **0** |
| Grok / DeepSeek drafts | 30 each in the plan | **0** |
| Labels per test set | ~22 per label | Thin: HEDGED, SUGGESTION, REPORTED and REFUSAL have **5 spans each**; CONDITIONAL has 6 |
| Audio clips | 30 | **0**; the audio set exists but `clips.jsonl` is empty |
| Ambiguous items reported apart | Yes | **Done**: the reports score them separately |
| Per-label precision/recall, confusion matrix, ledger F1, field accuracy, cost, p50/p95 | All | **Done**, in every report |
| Audio penalty | Ledger F1, audio vs text | **Not measured**, because there are no clips |
| Model comparison | Small, large, two-stage | **Haiku, Sonnet and Opus run** on test. Two-stage code exists (`two_stage.py`, `analyzer.py`) but has never been run |
| README results table | Per-configuration rows | **Stale**: it still shows only Haiku on the 24 dev items |
| Regression gate | CI fails on a drop of more than 2 points | **Done, the free way**: `eval-gate` checks committed reports against `baseline.json`. The live CI job is stubbed (`if: false`), by design |

## Latest test run (68 items)

| Model | Ledger F1 | Label accuracy | p50 / p95 | Cost for the run |
| --- | --- | --- | --- | --- |
| Opus | 1.000 | 0.974 | 2.7 s / 5.7 s | $0.51 |
| Sonnet | 0.980 | 0.935 | 2.0 s / 3.0 s | $0.21 |
| Haiku | 0.962 | 0.923 | 1.5 s / 2.2 s | $0.013 |

## Worth acting on

**The test set may be too easy.** Opus scored a perfect ledger F1, and the three models are only 4 points apart.
With 5 spans in a label, one mistake moves that label's recall by 20 points. More test items would make the
comparison meaningful, especially hand-written ones like the messy multi-turn dialogues, since the model-drafted
items seem to be the cleaner ones.

**The baseline doesn't gate Sonnet.** `baseline.json` gates only Opus and Haiku. That's fine if Sonnet is only
there for comparison, but it should be a deliberate choice.

## Next, in order

1. More test items: hand-written, plus Grok and DeepSeek drafts.
2. A two-stage run.
3. The audio clips.
4. The README results table, which is what people will actually look at; refresh it once the test set is
   closer to 150.
