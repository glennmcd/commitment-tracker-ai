# Evaluation guide

How evaluation data is made, scored and published. Every command runs from `backend/`. The design and its reasons
are in [plans/part-3-evaluation.md](plans/part-3-evaluation.md) and ADRs 0008–0013.

A typical cycle for one batch of drafted items, then a scored run:

```bash
uv run eval import ~/Downloads/gemini.jsonl --batch gem01 --provenance gemini-3-pro
uv run eval review --batch gem01
uv run eval promote --batch gem01 --to test
uv run eval --set test --config opus          # spends money on cache misses
uv run eval-gate --update-baseline            # only when a change in score is intended
uv run eval-export-site                       # then commit the reports, baseline and export
```

## Sets

Each set is a folder under `eval/sets/<name>/` with a manifest (`set.json`) and its items (`items.jsonl`):

| Set | Role | Gated | Holds |
| --- | --- | --- | --- |
| `dev` | tuning | no | the spec's 24 seed items and later dev items; Claude drafts are allowed here |
| `test` | headline | yes | reviewed drafts from Gemini, DeepSeek, Grok and GPT, plus hand-written items; never Claude drafts |
| `audio` | headline, audio | no | `clips.jsonl`: recordings of `test` items, pinned by SHA-256 |
| `staging/<batch>` | awaiting review | no | one imported batch, its review log and its import report |

Every item records who wrote it (`provenance`: `spec`, `hand-written` or `<family>-<model>`) and its review state
(`unreviewed`, `accepted` or `edited`). Only staging sets may hold unreviewed items.

A set is pinned by the SHA-256 of its items in canonical form (sorted keys, compact JSON, one item per line), so line
endings and key order never change it. Reports record the hash they ran against; the gate and the compare tool
refuse to mix versions.

`uv run eval-sets` lists every set with its role, size, hash prefix, review counts, label mix and provenance mix.
`--agreement` adds how often my blind labels agreed with each generator's.

The suite fails if a transcript appears in two sets, an id is used twice, a turn of six or more words from a non-dev
item is quoted in a prompt file, a Claude draft is in `test`, or an audio clip points at a missing item.

## Drafting items

[`eval/generation/prompt-v1.md`](../backend/eval/generation/prompt-v1.md) is the prompt for generator models. Fill
its placeholders and paste it into the chat app; save the reply as a `.jsonl` file.

- Use 25 items or fewer per batch, and an id prefix unique to the batch (`gem01`, `dsk02`).
- Vary the call date across batches: a Monday, a Friday, a date in the last week of a month, and one just before a
  month with fewer than 31 days. One date exercises one path through the date resolver.
- Target mix for `test` by primary label: COMMITMENT 25, HEDGED 20, CONDITIONAL 20, SUGGESTION 15, REQUEST 15,
  REPORTED 15, REFUSAL 15, NONE 25; about a third multi-turn.
- Hand-written batches go through the same import with `--provenance hand-written`. Aim them at what generators do
  badly: disfluent speech, sarcasm, deadlines tied to events, and assigned colleagues.

Change the generation prompt by adding `prompt-v2.md`. Import records the latest version unless
`--generation-prompt` says otherwise.

## Import

```bash
uv run eval import <file> --batch gem01 --provenance gemini-3-pro
```

Import skips Markdown fences and blank lines and validates every other line, listing each rejection with its line
number. It rejects ids already used and transcripts already in any set, and flags near duplicates (difflib ratio of
0.85 or more) for review rather than dropping them. Every due phrase is re-resolved by the extractor's date resolver;
a disagreement is recorded in `import.json` and shown in review, and the item keeps the generator's date until you
decide. The batch lands in `eval/sets/staging/gem01/` as unreviewed. An existing batch is never overwritten.

## Review

```bash
uv run eval review --batch gem01
```

For each item you see the call date and the transcript, then each expected span's turn and quote. Type a label
before the generator's is shown: `c` commitment, `h` hedged, `d` conditional, `s` suggestion, `r` request,
`p` reported, `x` refusal, `n` none.

- When every label agrees, enter accepts the item.
- On a disagreement you see both labels and the generator's note, then keep the generator's label (`g`), take yours
  (`m`, which marks the item `edited`) or reject it (`r`).
- A date disagreement asks whether the generator (`g`) or the resolver (`v`) is right. If the resolver is wrong, add
  a failing case to `tests/test_dates.py` and fix the resolver; don't patch the data around it.
- `e` opens the item in `$EDITOR` (or `$VISUAL`; Notepad on Windows) and re-validates it on save.
- `q` quits. Every decision is saved immediately, so a rerun picks up where you stopped.

Provenance stays hidden until the item is decided. `review.jsonl` keeps both labels per span, which is what the
agreement summary is computed from.

## Promote

```bash
uv run eval promote --batch gem01 --to test
```

Moves accepted and edited items into the target set and records the batch in its manifest. Rejected items and the
review log stay in staging. Every item must be decided first. Promoting into `test` changes its hash, so the gate
then wants a new report and baseline.

## Runs

```bash
uv run eval --set test --config opus
uv run eval --set test --model claude-opus-5-5 --prompt v1 --effort medium
```

`--config` names one of `haiku`, `sonnet`, `opus` and `two-stage` (`settings.CONFIGURATIONS`). Two-stage runs Haiku
over the whole transcript and sends each turn it labels anything but NONE, with two turns of context, to Opus; its
report adds the escalation rate (flagged turns over all turns, which predicts the saving on real calls) and screen
misses (expected ledger spans on turns Haiku didn't flag).

Responses are cached in `eval/.cache/` per stage, by transcript, model, prompt text and effort, so a rerun only pays
for what changed, and two-stage's screen reuses a Haiku run's responses. `--offline` answers only from the cache and
exits before calling anything if an item is missing; `--no-cache` always calls the model.

Reports go to `eval/reports/<set>/` as JSON and markdown. Runs with `--data` or on a staging batch go to
`eval/reports/adhoc/`, which is never gated or published. A run on `test` prints which prompt versions already have a
test report: tune prompts on `dev`, commit a version only when it is final, then run it on `test`.

`uv run eval rescore --set test` rebuilds a set's report scores from their stored predictions, offline, after a
change to the matching or metrics code. `uv run eval-compare <run-a> <run-b>` shows score changes between two runs on
the same set and the items that went from right to wrong and back.

## Audio

The audio set holds 30 clips of `test` items: 20 made with Polly and 10 read by two people. The clips live in the
private `EvalAudioBucket` (stack output `EvalAudioBucketName`; set it as `EVAL_AUDIO_BUCKET` or pass `--bucket`) and
in `eval/.audio/` once fetched.

```bash
uv run eval-audio make --item gem01-04 --item dsk01-11 --profile <p>
uv run eval-audio add hand01-03 recording.wav --readers seller=reader-1,buyer=reader-2
uv run eval-audio upload --profile <p>
uv run eval-audio fetch --profile <p>
uv run eval --set audio --transcribe --config opus --profile <p>
```

- Choose items with two speakers, at least 20 of them multi-turn, with every label represented. Give the human
  readings to the longer multi-turn items.
- Record human clips with the demo's recorder (16 kHz mono WAV) from the script, with two different readers. Readers
  are recorded as `reader-1`, `reader-2`, never by name.
- Every transfer checks the SHA-256 in `clips.jsonl`. Polly clips can be remade; human clips can't, and Polly never
  replaces one.
- `--transcribe` sends each clip to Amazon Transcribe once and caches the turns by audio hash, so later
  configurations transcribe nothing. Transcribed turns are aligned to the item's turns by shared words before
  scoring.
- The report's penalty is ledger F1 on the clips minus ledger F1 on the same items as text, for Polly, human and
  both. Turn-count mismatches, speaker errors and spans whose turn was lost are counted apart.

## The regression gate

`eval/baseline.json` lists, per gated set, the set hash and the scores of each gated configuration: `opus` (the
default model) and `haiku` (the deployed demo model). In CI, `uv run eval-gate` runs whenever the extractor,
evaluation code, settings, sets, reports or baseline change. It never calls a model. It fails when:

- no committed report matches the current prompt file, effort and set hash (it prints the command to run);
- the set's hash differs from the baseline's;
- ledger F1 dropped by more than 0.02 from the baseline, or any item failed;
- a report's stored scores differ from a re-score of its stored predictions.

Field-accuracy changes print as warnings. When a change in score is intended, run the gated configurations, then
`uv run eval-gate --update-baseline`, and commit the reports with the new baseline.

## Publishing

`uv run eval-export-site` writes the data behind the site's `/evals` pages to `frontend/src/data/evals/`. Run it after
any change to the sets or reports and commit the result; CI fails when it is stale. The pages need no password and
ask search engines not to index them, since they publish every test transcript.

## Costs

Measured on Haiku and estimated for the others from the same token counts (section 7 of the plan):

| Configuration | `test` (150 items) | `audio` (30 clips) |
| --- | --- | --- |
| Haiku | $0.03–0.05 | $0.01 |
| Sonnet | $0.49–1.35 | $0.10–0.27 |
| Opus | $0.98–2.70 | $0.20–0.54 |
| Two-stage | $0.90–2.45 | $0.18–0.49 |

Polly for 20 clips costs under $0.03 and Transcribe for 30 clips about $0.25, once. Opus and Sonnet output at medium
effort is unmeasured: run Opus on `dev` first and check its token counts before running `test`.
