# Current progress: evaluation

As of 2026-11-19 (v0.13.0, from `.release-please-manifest.json`), measured against the Evaluation plan in
[spec.md](spec.md).

The machinery is built: blind review, the regression gate, the reports and the comparison runs. What's left is
mostly data. Dev has 34 of its 50 items, test has 74 of 150, and none of the 30 audio clips exist yet.

Paths below are relative to `backend/eval/`. Set counts come from each set's `set.json`; scores come from the
reports named in the table under them.

| Spec item | Target | Where it stands |
| --- | --- | --- |
| Dev set | 50 items | **34** (24 spec + 10 hand-written), from `sets/dev/set.json` |
| Held-out test set | 150 items | **74** in `sets/test/set.json`: model-drafted and blind-reviewed Gemini 25, ChatGPT 22 + 21, plus 6 hand-written |
| Hand-written test items | 30 in the plan | **6** (batch `hw01`), from `sets/test/set.json` |
| Grok / DeepSeek drafts | 30 each in the plan | **0**: no batch in `sets/test/set.json` |
| Labels per test set | ~22 per label | Thin: HEDGED, SUGGESTION and REPORTED have **5 scored spans each**, REFUSAL 6 and CONDITIONAL 8 (support column of the Opus report below) |
| Audio clips | 30 | **0**; `sets/audio/clips.jsonl` is empty |
| Ambiguous items reported apart | Yes | **Done**: the reports score them separately (1 item in the current test set) |
| Per-label precision/recall, confusion matrix, ledger F1, field accuracy, cost, p50/p95 | All | **Done**, in every report |
| Audio penalty | Ledger F1, audio vs text | **Not measured**, because there are no clips |
| Model comparison | Small, large, two-stage | **Haiku and Opus run** on the 74-item test set, **Sonnet** only on the earlier 68-item version. Two-stage code exists (`two_stage.py`, `analyzer.py`) but no committed report comes from it |
| README results table | Per-configuration rows | **Current**: Haiku, Sonnet and Opus, each from its newest committed test report |
| Regression gate | CI fails on a drop of more than 2 points | **Done, the free way**: `eval-gate` checks committed reports against `baseline.json`, which gates Opus at ledger F1 0.900 and Haiku at 0.885. The live CI job is stubbed (`if: false`), by design |

## Latest test runs

| Model | Set | Ledger F1 | Label accuracy | p50 / p95 latency | Cost for the run | Report |
| --- | --- | --- | --- | --- | --- | --- |
| Opus | 74 items | 0.900 | 0.874 | 2870 / 7601 ms | $0.6250 | `reports/test/20261102T183807Z-claude-opus-5-5-v1.md` |
| Haiku | 74 items | 0.885 | 0.844 | 1597 / 2473 ms | $0.0161 | `reports/test/20261102T183701Z-claude-haiku-5-5-v1.md` |
| Sonnet | 68 items (earlier version) | 0.980 | 0.935 | 2029 / 2955 ms | $0.2110 | `reports/test/20261026T045729Z-claude-sonnet-5-5-v1.md` |

The Opus and Haiku ledger F1 match the gated values in `baseline.json`. Sonnet's row is not comparable with the
other two: it predates the hand-written items.

## Worth acting on

**The model-drafted items are too easy; the hand-written ones are not.** In the Opus report's By provenance table,
every model-drafted batch scores ledger F1 1.000 and the 6 hand-written items score 0.400. Haiku scores 0.444 on
them (its report, same table). So Opus's whole drop below 1.000 comes from six items. More hand-written items,
like the messy multi-turn dialogues, will make the comparison meaningful.

**The baseline doesn't gate Sonnet.** `baseline.json` gates only Opus and Haiku, and Sonnet has not been run on the
current test set. That's fine if Sonnet is only there for comparison, but it should be a deliberate choice.

## Next, in order

1. More test items: hand-written first, plus Grok and DeepSeek drafts.
2. A Sonnet run on the current test set, so the README compares all three models on the same items.
3. A two-stage run.
4. The audio clips.
