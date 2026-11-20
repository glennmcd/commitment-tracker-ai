# Current progress: evaluation

As of 2026-11-19 (v0.13.0, from `.release-please-manifest.json`), measured against the Evaluation plan in [spec.md](spec.md).

The machinery is built: blind review, the regression gate, the reports and the comparison runs. What's left is
mostly data. Dev has 34 of its 50 items, test has 74 of 150, and none of the 30 audio clips exist yet.

Counts come from `backend/eval/sets/*/items.jsonl` and each set's `set.json`. Targets come from [spec.md](spec.md).
Scores come from the `scores` section of the newest report in `backend/eval/reports/`.

| Spec item | Target | Where it stands |
| --- | --- | --- |
| Dev set | 50 items | **34** (24 spec + 10 hand-written) in `sets/dev/items.jsonl`. The newest dev report, `reports/dev/20261022T040145Z-claude-haiku-5-5-v1.json`, scores only the 24 seed items |
| Held-out test set | 150 items | **74** per `sets/test/set.json`: Gemini 25, ChatGPT 22 + 21 (model-drafted, blind-reviewed), hand-written 6 |
| Hand-written test items | 30 in the plan | **6** (batch `hw01`) |
| Grok / DeepSeek drafts | 30 each in the plan | **0** |
| Labels per test set | ~22 per label | Thin: HEDGED, SUGGESTION and REPORTED have **5 spans each**, REFUSAL 6, CONDITIONAL 8 (the label rows of the Nov 2 Haiku and Opus reports) |
| Audio clips | 30 | **0**; `sets/audio/clips.jsonl` is empty |
| Ambiguous items reported apart | Yes | **Done**: the reports score them separately (one per test run) |
| Per-label precision/recall, confusion matrix, ledger F1, field accuracy, cost, p50/p95 | All | **Done**, in every report |
| Audio penalty | Ledger F1, audio vs text | **Not measured**, because there are no clips |
| Model comparison | Small, large, two-stage | **Haiku, Sonnet and Opus have test reports**. Two-stage code exists (`extractor/two_stage.py`, `extractor/analyzer.py`) but no committed report has a two-stage run |
| README results table | Per-configuration rows | **Current**: its rows match the newest reports (checked 2026-11-19). Its Sonnet row is from an earlier 68-item set |
| Regression gate | CI fails on a drop of more than 2 points | **Done, the free way**: `eval-gate` checks committed reports against `backend/eval/baseline.json`, which gates Opus and Haiku on test. The live CI job is stubbed (`if: false` in `.github/workflows/ci.yml`), by design |

## Latest test runs

| Model | Report | Items | Ledger F1 | Label accuracy | Field accuracy (owner / action / due) | p50 / p95 | Cost for the run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Opus | `20261102T183807Z-claude-opus-5-5-v1.json` | 74 | 0.900 | 0.874 | 27/27, 22/26, 26/27 | 2870 / 7601 ms | $0.6250 |
| Sonnet | `20261026T045729Z-claude-sonnet-5-5-v1.json` | 68 (earlier set) | 0.980 | 0.935 | 25/25, 22/24, 24/25 | 2029 / 2955 ms | $0.2110 |
| Haiku | `20261102T183701Z-claude-haiku-5-5-v1.json` | 74 | 0.885 | 0.844 | 27/27, 22/26, 26/27 | 1597 / 2473 ms | $0.0161 |

The Opus and Haiku ledger F1 values are the gated values in `backend/eval/baseline.json` (0.900 and 0.885). The
README's Results table shows the same rows.

## Worth acting on

**The test set is still too small to separate the models.** Opus and Haiku differ by 1.5 ledger F1 points (0.900 and
0.885) on the same 31 ledger spans. With 5 spans in a label, one mistake moves that label's recall by 20 points: Haiku's
HEDGED recall of 0.600 is 2 misses out of 5. More test items would make the comparison meaningful, especially
hand-written ones like the messy multi-turn dialogues.

**The Sonnet row isn't comparable.** Its report covers the earlier 68-item test set (sha256 `6cd5dd1ad6a9`). The
current set (sha256 `419f2ad60517`) has 74 items, so its 0.980 can't be set against Opus's 0.900 or Haiku's 0.885. It
isn't gated either: `baseline.json` gates only Opus and Haiku. That's fine if Sonnet is only there for comparison, but
it should be a deliberate choice.

**Cost and latency differ a lot.** On these runs Opus cost about 39 times what Haiku did ($0.6250 against $0.0161),
and its p95 latency was about 3 times Haiku's (7601 ms against 2473 ms).

## Next, in order

1. More test items to reach 150: the 24 hand-written items still missing from the plan's 30, plus Grok and DeepSeek
   drafts (30 each in the plan).
2. Re-run Sonnet on the current 74-item test set, so its row can be compared with Opus and Haiku.
3. A two-stage run. No committed report has one yet.
4. The audio clips (0 of 30).
5. The README results table is current. Refresh it when the test set is closer to 150.
