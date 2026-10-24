# Part 3: evaluation sets, model comparison and the regression gate

Oct 23, 2026 · Accepted

How Part 3 turns "1.000 on 24 tuned examples" into a measured result. Evaluation data moves into named, hashed
sets; held-out items are drafted mostly by non-Claude models and reviewed blind; 30 test items get audio; three
configurations are compared on the test set; a gate in CI checks committed reports without spending anything; and
a read-only `/evals` section of the site shows the results. This document settles the seven design questions in
`docs/part-3-brief.md`, reviews `backend/eval/generation/prompt-v1.md`, then lays out the file tree and the commit
sequence.

Every number below comes from the repository: token counts from the 24 cached Haiku responses in
`backend/eval/.cache/`, prices from `extractor/pricing.py`, and the report shape from `evaluation/report.py`.
Transcribe and Polly prices are the ones Part 2 used; confirm them on the AWS pricing pages before the audio run.

## Summary

| Decision | Choice |
| --- | --- |
| Set layout | `backend/eval/sets/<name>/` with `items.jsonl` and `set.json`; `dev`, `test`, `audio`, `staging/<batch>` |
| Set hash | SHA-256 of the items in **canonical form** (each line re-serialised with sorted keys), so line endings and key order can't change it; `.gitattributes` also pins `eol=lf` |
| Migration | `eval/data/dev.jsonl` → `eval/sets/dev/items.jsonl` with `provenance: spec`, `review: accepted`. `--data` keeps working. The existing report moves to `eval/reports/dev/` and is shown as a pre-set legacy run |
| Test-set authors | 150 items: **30 each hand-written, Gemini, DeepSeek, Grok and GPT**. **No Claude drafts in `test`**; Claude drafts are allowed in `dev` only |
| Blind review | Transcript first, my label per span, then the generator's label. Provenance is hidden until the item is decided |
| Audio items | **A mix: 20 Polly clips and 10 human recordings**, scored and reported separately. Audio lives in a private S3 bucket in the project account, pinned by SHA-256 in a committed manifest |
| Two-stage pipeline | Haiku runs the full v1 extraction; **turns it labels anything but NONE are re-extracted by Opus** with up to two preceding turns as context. A `TwoStageExtractor` in `extractor/`, same `analyze()` contract, no API shape change |
| Regression gate | The brief's report-required design, **plus** two cheap additions: reports store predicted spans so the gate **re-scores them with the current metrics code**, and the gate covers both the **default model** (Opus) and the **deployed demo model** (Haiku) |
| Evaluation pages | `/evals`, `/evals/runs/[run]`, `/evals/runs/[run]/items`, `/evals/compare`, built statically from JSON that `uv run eval-export-site` writes under `frontend/src/data/evals/`; CI fails when it is stale |
| Configurations | **Haiku, Sonnet, Opus and two-stage.** Sonnet costs under $1.40 on `test` and shows whether Opus's gain needs Opus |
| Cost of the full comparison | About **$3–8** for four configurations on `test` and `audio` (table in section 7) |
| New dependencies | **None.** Review uses `input()` and `$EDITOR`; turn alignment uses `difflib`; audio fetch uses boto3 (already a dependency); the pages use plain CSS |

## 1. Evaluation-set layout

```text
backend/eval/
  sets/
    dev/       set.json  items.jsonl            role dev,  gated: false
    test/      set.json  items.jsonl            role test, gated: true
    audio/     set.json  clips.jsonl            role test, kind audio, points at test ids
    staging/
      gem01/   set.json  items.jsonl  review.jsonl  import.json
  generation/  prompt-v1.md                     generation prompts, versioned like extractor prompts
  baseline.json
  reports/
    dev/   <run>.json  <run>.md
    test/  ...
    audio/ ...
```

**Manifest (`set.json`).** Validated by a Pydantic model with `extra="forbid"`:

```json
{
  "name": "test",
  "description": "Held-out headline set: reviewed drafts from non-Claude models plus hand-written items.",
  "role": "test",
  "gated": true,
  "sources": [
    {"batch": "gem01", "provenance": "gemini-3-pro", "generation_prompt": "prompt-v1",
     "call_date": "2026-11-04", "imported": "2026-10-25", "promoted": "2026-10-26", "items": 23},
    {"batch": "hand01", "provenance": "hand-written", "generation_prompt": null, "items": 12}
  ]
}
```

The manifest records where batches came from; each item still carries its own `provenance` and `review`, so a
report can break scores down without reading manifests. The audio manifest adds `"kind": "audio"` and
`"items_from": "test"`.

**Item fields.** `EvalItem` gains `provenance: str` (pattern `spec|hand-written|<family>-<model>`) and
`review: Literal["unreviewed", "accepted", "edited"]`, both required, `extra="forbid"` unchanged. Loading a set
other than `staging/*` rejects `unreviewed` items.

**Hash.** `set_sha256` is computed over the canonical form: every item parsed, dumped with `sort_keys=True`,
compact separators and `ensure_ascii=False`, joined with `\n`. This matters on this machine: a Windows checkout
with `core.autocrlf` would otherwise hash differently from CI's Linux checkout, and the gate would fail for a set
nobody changed. A `.gitattributes` line (`backend/eval/** text eol=lf`) keeps the files themselves stable too.

**Reports pin the set.** `RunInfo` gains `set_name`, `set_sha256`, `set_items`, and `configuration` (section 4).
`dataset` stays for `--data` runs. Reports are written to `eval/reports/<set>/`; a `--data` run goes to
`eval/reports/adhoc/` and is never gated or shown on the site.

**Migration.**

- `git mv eval/data/dev.jsonl eval/sets/dev/items.jsonl`, adding `provenance: "spec"` and `review: "accepted"` to
  the 24 items. `DEV_PATH` points at the new file, so `uv run eval --data <file>` and the default behave as
  before.
- The Haiku report moves to `eval/reports/dev/`. It has no set hash, so the site labels it "legacy, before sets"
  and the gate ignores it. Its file stays byte-for-byte as written.
- `--set` and `--data` are mutually exclusive; with neither, `--set dev` is the default.

**Commands.**

- `uv run eval --set <name>` runs a set. `uv run eval --set staging/gem01` is allowed for a sanity run but its
  report is written to `adhoc/`.
- `uv run eval-sets` prints one row per set: role, gated, items, review counts, label mix (by span), provenance
  mix, and hash prefix.

**Leak test** (`tests/test_sets.py`, offline, runs in the normal suite):

- No transcript appears in more than one set (`audio` excluded; it holds ids, not transcripts). Transcripts are
  compared after normalising case, whitespace and punctuation.
- No turn of a non-dev item with six or more words appears in any file under `extractor/prompts/`. The six-word
  floor keeps "Will do." from matching every prompt.
- Every `audio` clip points at an existing `test` id, and no id appears in two sets.

## 2. Authoring and labeling

**The mix.**

| Set | Spec | Hand-written | Gemini | DeepSeek | Grok | GPT | Claude |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `dev` (50) | 24 | 10 | 0 | 0 | 0 | 0 | 16 |
| `test` (150) | 0 | 30 | 30 | 30 | 30 | 30 | 0 |

- The extractor is Claude. A Claude-drafted test item tends to phrase commitments the way Claude reads them, which
  flatters the score, so `test` holds none. `dev` may use Claude drafts: it is the tuning set and its score is
  never a headline.
- Four generator families (Gemini, DeepSeek, Grok, GPT) at 30 items each, so the provenance breakdown can show
  whether any one family's items are easier or harder for the extractor. That is two batches per family (25 and
  a top-up, before rejects). Provenance values: `gemini-<model>`, `deepseek-<model>`, `grok-<model>`,
  `gpt-<model>`. As with the others, Grok and GPT are used through their chat apps; no keys or SDKs are added.
- Hand-written items target what generators produce badly: speech disfluency, sarcasm, deadlines tied to events,
  and assigned colleagues.
- Target span mix for `test` (primary label per item): COMMITMENT 25, HEDGED 20, CONDITIONAL 20, SUGGESTION 15,
  REQUEST 15, REPORTED 15, REFUSAL 15, NONE 25 (mostly keyword traps). About a third multi-turn.
- **Vary `{{CALL_DATE}}` across batches**: a Monday, a Friday, a date in the last week of a month, and one before
  a month with fewer than 31 days. One fixed date would exercise one path through the resolver.

**Import** (`uv run eval import <file> --batch <name> --provenance <generator>`):

1. Strips Markdown fences and blank lines (Gemini adds fences despite the instruction), then validates every line
   with the dataset rules and collects every rejection with its line number and reason; it never stops at the
   first.
2. Drops exact duplicates of any item in any set (normalised transcript). Flags near-duplicates (`difflib` ratio
   ≥ 0.85 against any existing transcript) for review instead of dropping them, since generators often lightly
   vary the prompt's own examples.
3. Recomputes `due_resolved` with `extractor.dates` for every span with a `due_raw`. A disagreement is stored in
   the batch's `import.json` as `{"item", "span", "generator", "resolver"}` and shown in review; the item keeps
   the generator's date.
4. Writes the rest to `staging/<batch>/items.jsonl` as `unreviewed`, with `provenance` set, and writes the
   manifest with the generation prompt version (`--generation-prompt`, default the latest file).

Ids are kept as the generator wrote them (`gem01-07`); a collision with any existing id is a rejection.

**Review** (`uv run eval review --batch <name>`), a plain terminal loop with `input()`:

- Shows the call date and transcript only. For each expected span it shows the turn and the quote and asks for
  my label (single keys: `c h d s r p x n`, i.e. commitment, hedged, conditional, suggestion, request, reported,
  refusal, none). Provenance and the generator's note stay hidden until the item is decided.
- If every span matches, `enter` accepts. A disagreement shows both labels and the generator's note; I keep the
  generator's label, take mine (the item becomes `edited`), or reject the item. Date disagreements from import are
  shown the same way, and I decide whether the generator or the resolver is wrong. A resolver bug becomes a
  failing test in `test_dates.py`, not a silent fix.
- `e` opens the item in `$EDITOR` (via `subprocess.run([editor, path])`, no shell), re-validates on save and
  loops until it validates or I discard the edit.
- Progress is written after every item, so quitting and resuming loses nothing.
- `review.jsonl` records, per span, my label, the generator's label, the outcome and timestamps. `eval-sets
  --agreement` turns these into agreement per generator and per label (raw agreement and Cohen's kappa, which
  scikit-learn already provides).

**Promote** (`uv run eval promote --batch <name> --to test`) moves `accepted` and `edited` items into the target
set, appends the batch to its manifest's `sources`, and leaves rejected items and the review log in staging.
Promoting into a gated set prints the new hash and says that the gate now wants a new report and baseline.

**Keeping test out of tuning.**

- The leak test above catches the mechanical leak (test text pasted into a prompt).
- The process rule: prompt drafts are iterated on `dev` only, without committing; a prompt version is committed
  when it's final, and only then run on `test`. The report-required gate makes every test run visible as a
  committed report, so the number of test runs per prompt version is on the record.
- `eval --set test` prints how many prompt versions already have a `test` report, as a reminder that every look
  spends some of the set's independence.

**Review of `eval/generation/prompt-v1.md`.** The prompt is solid: the label table and decision rules match
`docs/spec.md`, the field rules match `ExpectedSpan`, and the self-check list targets the commonest generator
mistakes. Changes for a `prompt-v2.md`, none blocking for the first batches:

- **Named dates.** The resolver resolves "October 30" to the next one on or after the call date; the prompt has no
  rule for named dates, so generators will guess.
- **"Next month"** is vague (no date) in the resolver; the prompt doesn't say so and generators may resolve it.
- **Speaker ids.** Say explicitly that `speaker`, `owner` and `recipient` use the two ids exactly as given, and
  that only third parties and assigned colleagues appear by name.
- **One call date per batch** is fine for the prompt, but the docs must tell me to vary it (above).

The import's resolver check catches the date gaps either way, so v1 can be used as is.

## 3. Audio items

**Options.**

| | Polly only | Own recordings only | Mix (recommended) |
| --- | --- | --- | --- |
| Transcript fidelity | Exact: the script is the transcript | Close if read from the script; ad-libs break expected quotes | Both, reported separately |
| Transcription penalty | Understated: clean audio, distinct synthetic voices, no overlap | Realistic: room noise, laptop mic, natural pace | The human slice shows the real penalty; the Polly slice isolates diarization and ASR on clean audio |
| Regeneration | Script, ~$0.04 | Can't be regenerated; must be fetched | Polly regenerated, human fetched |
| Effort for you | None | Two speakers reading 30 dialogues | Two speakers reading 10 |
| Privacy | None | Your voice and a second person's | Same, for 10 clips |

**Recommendation: the mix, 20 Polly and 10 human.** Polly alone would make the audio penalty look smaller than any
real call; human only is a lot of recording for a portfolio project. The README reports the penalty for each
slice, so the reader sees how much Polly understates it.

- **Choosing items.** 30 `test` items, at least 20 multi-turn (diarization only matters with two speakers) and
  every label represented. The 10 human items are the longer multi-turn ones.
- **Human recordings** have two different speakers in every clip (confirmed), so diarization is tested on human
  audio too. Each clip is read from the script with natural delivery, recorded with the demo's own Recorder
  (16 kHz mono WAV, the production format) and saved locally. Small slips are fine; scoring tolerates them
  (below). `clips.jsonl` records which speaker read which role, by role id only, never by name.
- **Polly clips** reuse `scripts/make_samples.py`'s synthesis (two standard voices, 400 ms gaps), refactored into
  a function that `eval-audio make` calls.
- **Storage.** A private, versioned S3 bucket `EvalAudioBucket` in the API stack (no lifecycle expiry, unlike the
  upload bucket), deployed by you. `clips.jsonl` records each clip's `test_item_id`, `source` (`polly` or
  `human`), voices, duration and SHA-256. `uv run eval-audio fetch --profile <p>` downloads into
  `eval/.audio/` (git-ignored) and checks hashes; `eval-audio make` regenerates the Polly clips and
  `eval-audio upload` pushes new clips. I'd rather not use a GitHub release: it would publish two people's voices.
- **Scoring.** `uv run eval --set audio --transcribe` transcribes each clip with the existing `AwsTranscriber`
  (batch, speaker labels) and caches the turns by audio hash in `eval/.cache/transcripts/`, so Transcribe runs
  once per clip. Transcribed turns are aligned to the item's turns with `difflib.SequenceMatcher` over words: each
  transcribed turn maps to the item turn it shares the most words with, and speaker labels map by majority.
  Expected spans are then matched by the existing word-overlap rule (≥ 0.6), which already tolerates small ASR
  differences. A report records turn-count mismatches and speaker swaps as their own counts.
- **The penalty** is ledger F1 on the transcribed clips minus ledger F1 on the same 30 items as text, per
  configuration and per slice. The text side reuses the `test` run's cached responses, so it costs nothing.

## 4. Two-stage pipeline

**Shape.** Screening needs Haiku's labels per turn, and the extract stage must see enough context for
multi-turn labels ("Sure, I'll do it" after a request).

1. **Screen.** Haiku runs the unchanged v1 extraction on the whole transcript.
2. **Flag.** Every turn where Haiku returned a span with a label other than NONE is flagged. The flag set is a
   setting (`two_stage_flag_labels`), so a stricter rule (ledger labels only) can be tested without code changes.
3. **Extract.** Flagged turns, each with up to two preceding turns, are merged into contiguous windows. Each
   window goes to Opus as its own sub-transcript with the same v1 prompt. Turn indices are remapped back, spans
   on context-only turns are discarded, and the quote check runs against the original turns.
4. **Merge.** Opus spans replace Haiku's on flagged turns; Haiku's spans stand on the rest (all NONE by
   construction, so they never reach the ledger).

Item-level escalation (re-run the whole transcript on Opus if anything is flagged) is simpler, but a real call
almost always contains one commitment, so it would escalate nearly every call and save nothing. The window keeps
Opus's output tokens, the expensive part at $20 per million, to the flagged turns. Reusing v1 for both stages
means no new prompt to tune.

**Where it lives.**

- `extractor/analyzer.py` defines `Analyzer`, a Protocol with `async analyze(request) -> AnalyzeResponse` and a
  `describe() -> Configuration` (name, stage models, prompt version and hash, effort). `Extractor` already
  satisfies the first half.
- `extractor/two_stage.py` holds `TwoStageExtractor(screen: Analyzer, extract: Analyzer, flag_labels)`. It imports
  only `schemas` and other `extractor` modules, so the layering test is unchanged.
- `extractor/factory.py` gains `build_analyzer(settings, configuration)`, where `configuration` is `haiku`,
  `sonnet`, `opus` or `two-stage`, mapped to model ids in one table. `--model <id>` keeps working.
- The evaluation cache wraps each stage, not the pipeline: `evaluation/cache.py` gains `CachedAnalyzer`, which
  `run_items` hands to `TwoStageExtractor` for each stage. The screen stage's key is identical to the Haiku
  configuration's, so after a Haiku run the screen stage costs nothing. Opus windows have their own keys.
- The API keeps the single-model `Extractor`, and `AnalyzeResponse` doesn't change, so `API_VERSION` stays.
  Metadata for a two-stage response sums tokens and cost over both stages, sets `model` to the configuration name
  and `served_by` to the extract model when anything was escalated.

**Reporting it as one run.** `TwoStageExtractor.analyze_detailed()` returns the response plus per-stage usage,
latency and the flagged turn count. The report's per-item record keeps stage costs and latencies; headline cost
per clip is the sum, and latency is the item's wall clock (stages are sequential), so p95 is over real
end-to-end times. The report adds **escalation rate** (flagged turns / turns) and **screen misses** (expected
ledger spans on turns the screen did not flag), the number that says whether Haiku is a safe screen.

The eval sets are built around labels, so nearly every item has a flagged turn and the measured saving will be
small. The README says so and gives the escalation rate, which is what predicts the saving on real calls.

## 5. The regression gate

**Confirmed: report-required, as the brief describes.** CI never calls a model; it checks that someone has run
the evaluation locally and committed the report, and that the report doesn't regress against `baseline.json`.

`eval/baseline.json`:

```json
{
  "sets": {
    "test": {
      "set_sha256": "…",
      "configurations": {
        "opus":  {"model": "claude-opus-5-5",  "effort": "medium", "prompt_version": "v1",
                  "prompt_sha256": "…", "report": "eval/reports/test/<run>.json",
                  "ledger_f1": 0.0, "field_accuracy": {"owner": 0.0, "action": 0.0, "due": 0.0},
                  "failed_items": 0},
        "haiku": {"…": "…"}
      }
    }
  }
}
```

`uv run eval-gate` is a pure function over the committed files. For each gated set and each configuration in the
baseline it:

1. Takes the **current** configuration: the default model and effort from the `Settings` field defaults (not the
   environment), the default prompt version and its file's hash.
2. Finds the latest committed report whose configuration, prompt hash and set hash all match. None found fails
   with the exact command to run (`uv run eval --set test --config opus`).
3. Fails if the set hash differs from the baseline's ("the set changed; re-baseline on purpose"), if ledger F1
   dropped by more than 0.02 (`baseline − current > 0.02` after rounding both to six places, so exactly 0.02
   passes), or if any item failed. Field-accuracy changes print as warnings.

**Two additions, both free in CI.**

- **Re-score committed reports.** Today's `ItemDetail` keeps only label lists, so a change to `matching.py` or
  `metrics.py` would leave every committed score stale and the gate would compare stale numbers. Reports will
  store each item's predicted spans (the fields scoring reads, plus `dropped_quotes` and `error`). The gate
  rebuilds the scores from those spans and the current set items with the current metrics code, and fails if
  they differ from the stored scores. `uv run eval rescore --set <name>` rewrites reports offline from their
  stored predictions. The site needs the predicted spans anyway (section 6).
- **Gate the demo model too.** The default model is Opus, but the deployed demo runs `claude-haiku-5-5`
  (`DEFAULT_DEMO_MODEL` in `infra/lib/api-stack.ts`). A prompt change that breaks Haiku would pass a gate that
  looks only at Opus. The baseline lists both configurations, and a test reads `DEFAULT_DEMO_MODEL` from the
  stack source and checks the baseline covers it. A Haiku test run costs about $0.04.

**`uv run eval --offline`** wraps the cache so a miss raises `CacheMiss` and the run exits non-zero before any
adapter is built; with `--offline`, no API key is read at all.

**CI.** A job `eval-gate` in `ci.yml` with no secrets and `permissions: contents: read`. A path filter inside a
job needs a third-party action, and a workflow-level `paths:` filter leaves a required check pending when it
doesn't run. So the job always runs and its first step checks `git diff --name-only` against the base for
`extractor/prompts/`, `settings.py`, `extractor/`, `evaluation/`, `eval/sets/`, `eval/reports/` and
`eval/baseline.json`; with no match it exits successfully in seconds. `dev` is not gated: it changes while
prompts are being tuned, and gating it would mean re-baselining constantly.

**The live job (stub).** `eval-live` in `ci.yml`, `on: workflow_dispatch`, `if: false`, with its steps written out
and commented: restore the response cache, `uv run eval --set test --config <c>` per configuration, upload the
reports as an artifact. A comment lists what enabling it needs: an `ANTHROPIC_API_KEY` in a protected
environment with required reviewers, a spend cap on the key, cache restore between runs, and the per-run cost
from section 7.

## 6. The evaluation pages

**Routes** (static export; every dynamic segment comes from `generateStaticParams` over the exported data):

| Route | Content |
| --- | --- |
| `/evals` | Results table per set (one row per configuration's latest run), the sets with role, items, review status, label and provenance mix, and the audio penalty |
| `/evals/runs/[run]` | Headline scores, per-label table, confusion matrix, field accuracy, scores by provenance, screen misses and escalation rate (two-stage), failed items, configuration, prompt, set hash, cost and latency |
| `/evals/runs/[run]/items` | Filters for label, tag, provenance and right or wrong. Each item shows the transcript with expected and predicted spans side by side, mismatched fields marked with text and an icon, plus dropped quotes and errors |
| `/evals/compare` | Two runs on the same set, chosen from two selects and kept in the query string (`?a=…&b=…`): score changes, and the items that went from right to wrong and back |

`[run]` is the report's file stem. Filters and the compare selection are client-side, since a static export has no
request-time rendering; `useSearchParams` sits inside a `Suspense` boundary, as a static export requires.

**Data.** `uv run eval-export-site` reads `eval/sets/` and `eval/reports/` (not `adhoc/`) and writes:

- `frontend/src/data/evals/index.json`: sets, results tables and a run list.
- `frontend/src/data/evals/runs/<run>.json`: one run's scores and its items joined with their transcripts and
  expected spans.

The pages import these at build time; nothing is fetched at run time. The output is written with sorted keys and
fixed float rounding so the export is deterministic. The backend CI job runs the export and `git diff
--exit-code -- frontend/src/data/evals`, the same pattern as `openapi.json`. Frontend types for the data come from
a hand-written `src/lib/evals.ts`, checked by a Vitest test that loads the committed export.

**Outside the gate.** `PasswordGate` wraps only `<Demo />` on `/`. The `/evals` pages are separate routes that
never render it, so they need no password. The home page header and the README link to `/evals`.

**Accessibility.** The confusion matrix is a `<table>` with `<th scope>` headers and the count in every cell;
shading is a background tint added to the number, never in place of it. Right and wrong are marked by text and an
icon, not colour. Filters are native `<select>` and checkbox controls. Below 640 px the matrix scrolls inside its
own container, and the item comparison stacks expected above predicted.

**Tests.** Vitest component tests against two fixture reports (one single-model, one two-stage), covering the
matrix, the filters and the compare diff. One Playwright test opens a run, then an item, without the password.

## 7. Run cost

**Measured per item (Haiku 5.5, prompt v1, effort medium, 24 dev items):** 79 input, 186 output, 5,942
cache-read and 258 cache-write tokens on average (the 6,200-token system prompt is written once and read on every
later call). That's $0.000193 per item, which matches the report's $0.0046 total.

**Assumptions for the other models.** The same token counts, priced from `pricing.py`, give the low estimate. The
high estimate doubles input and output for longer generated items, and doubles output again for Opus and Sonnet,
whose output at medium effort is not yet measured. The first Opus run on `dev` replaces the assumption with a
measurement before you run `test`.

| Configuration | Per item | `dev` (50) | `test` (150) | `audio` (30, transcribed) |
| --- | --- | --- | --- | --- |
| Haiku | $0.0002–0.0003 | $0.01–0.02 | $0.03–0.05 | $0.01 |
| Sonnet | $0.003–0.009 | $0.16–0.45 | $0.49–1.35 | $0.10–0.27 |
| Opus | $0.007–0.018 | $0.33–0.90 | $0.98–2.70 | $0.20–0.54 |
| Two-stage (Haiku screen, Opus on ~90% of eval items) | $0.006–0.016 | $0.30–0.82 | $0.90–2.45 | $0.18–0.49 |

Two-stage's screen costs nothing after a Haiku run (shared cache keys); its Opus windows don't share keys with the
Opus run.

**Audio extras, once:** Polly for 20 clips of about 300 characters at $4 per million characters is under $0.03.
Transcribe bills per second with a 15-second minimum per job; 30 clips of about 20 s at $0.024 per minute is about
$0.25. Transcripts are cached, so the four configurations share one transcription pass.

**The whole comparison** (four configurations on `test` and on `audio`, plus Polly and Transcribe): about **$3.20
at the low estimate and $8.10 at the high**. Without Sonnet, $2.60–6.50. Re-running anything already cached is
free.

## Backend changes

- `evaluation/dataset.py`: `provenance`, `review`; `load_set(name)` returning items, manifest and hash;
  `canonical_sha256`.
- `evaluation/sets.py`: manifest model, set discovery, `eval-sets` output, leak helpers.
- `evaluation/importer.py`, `evaluation/review.py`, `evaluation/promote.py`: the batch workflow. The review loop
  takes injected `input`/`print`/editor functions so it is tested without a terminal.
- `evaluation/cli.py`: `--set`, `--config`, `--offline`, `--transcribe`; subcommands `import`, `review`,
  `promote`, `rescore` dispatched before the run parser, so `uv run eval --set test` and `uv run eval import f`
  both work.
- `evaluation/report.py`: `RunInfo` set and configuration fields; `ItemDetail` predicted spans, per-stage cost
  and latency; scores by provenance; escalation rate and screen misses. Old reports still load (new fields have
  defaults).
- `evaluation/compare.py` (`eval-compare`), `evaluation/gate.py` (`eval-gate`), `evaluation/site_export.py`
  (`eval-export-site`), `evaluation/audio.py` (`eval-audio`, alignment, transcript cache).
- `extractor/analyzer.py`, `extractor/two_stage.py`, `extractor/factory.py`: section 4.
- `settings.py`: `two_stage_flag_labels`, the configuration table.
- `pyproject.toml`: the new scripts. No new dependencies.

Logging stays as before: ids, counts, labels, latency, tokens. The review tool prints transcripts to the terminal,
which is its job, but never logs them.

## File tree (new and changed)

```text
.gitattributes                                  backend/eval/** text eol=lf
.github/workflows/ci.yml                        eval-gate job, eval-live stub, export staleness check
.gitignore                                      backend/eval/.audio/
CLAUDE.md                                       layout and commands
README.md                                       results, audio penalty, provenance, agreement, failure analysis
docs/plans/part-3-evaluation.md                 this document
docs/decisions/0008-evaluation-sets.md          one ADR per accepted decision
docs/decisions/0009-non-claude-held-out-items.md
docs/decisions/0010-audio-evaluation-items.md
docs/decisions/0011-two-stage-pipeline.md
docs/decisions/0012-report-required-gate.md
docs/decisions/0013-static-evaluation-pages.md
docs/evaluation.md                              sets, generation, import, review, promote, runs, costs, baseline
backend/pyproject.toml                          eval-sets, eval-compare, eval-gate, eval-export-site, eval-audio
backend/eval/sets/{dev,test,audio}/             set.json + items.jsonl (clips.jsonl for audio)
backend/eval/sets/staging/<batch>/              per imported batch
backend/eval/generation/prompt-v1.md            already written
backend/eval/baseline.json
backend/eval/reports/{dev,test,audio}/
backend/eval/data/dev.jsonl                     moved to sets/dev/items.jsonl
backend/scripts/make_samples.py                 synthesis moved into a reusable function
backend/src/commitment_tracker/
  settings.py
  extractor/{analyzer,two_stage,factory}.py
  evaluation/{dataset,sets,importer,review,promote,cli,report,compare,gate,site_export,audio,cache}.py
backend/tests/                                  test_sets (leak), test_importer, test_review, test_promote,
                                                test_two_stage, test_gate, test_compare, test_site_export,
                                                test_audio_alignment, test_offline_cache
frontend/src/data/evals/                        generated, committed
frontend/src/app/evals/{page,runs/[run]/page,runs/[run]/items/page,compare/page}.tsx
frontend/src/components/evals/                  ResultsTable, ConfusionMatrix, ScoreBars, ItemDiff, Filters
frontend/src/lib/evals.ts                       data types and selectors
frontend/e2e/evals.spec.ts
infra/lib/api-stack.ts                          EvalAudioBucket (private, versioned)
infra/test/stacks.test.ts
```

## Commit sequence

Small, test-first where practical, Conventional. `feat:` for new commands and the pages.

1. `docs: add the Part 3 design` (this document)
2. `docs: add ADRs 0008–0013` (after approval)
3. `refactor(eval): move the dev set to eval/sets with provenance and review`
4. `feat(eval): add set manifests, canonical hashes and --set`
5. `feat(eval): add eval-sets`
6. `test(eval): fail when items leak across sets or into prompts`
7. `feat(eval): add batch import with resolver checks`
8. `feat(eval): add blind review`
9. `feat(eval): add promote and the review agreement summary`
10. `feat(eval): store predicted spans and scores by provenance in reports`
11. `feat(eval): add --offline and rescore`
12. `feat: add the two-stage extractor` (analyzer protocol, factory, per-stage cache, report fields)
13. `feat(eval): add eval-compare`
14. `feat(eval): add eval-gate and the baseline`
15. `ci: add the eval-gate job and the disabled live evaluation job`
16. `feat(infra): add the evaluation audio bucket`
17. `feat(eval): add eval-audio make, upload and fetch`
18. `feat(eval): score transcribed audio against text items`
19. `feat(eval): add eval-export-site`
20. `feat(web): add the evaluation overview and run pages`
21. `feat(web): add the items and compare pages`
22. `ci: fail when the exported evaluation data is stale`
23. `docs: add the evaluation guide`

Your work, interleaved: generate and import batches after 7, review after 8, promote after 9, deploy the bucket
after 16 and record the human clips after 17. After 18, you run the four configurations on `test` and `audio`;
then `chore(eval): add test-set reports and the baseline` and `docs: add test-set results to the README`.

## Risks

- **Review is the bottleneck.** 150 test items plus 26 dev items at a minute or two each is four to six hours of
  your time, before rejects. Batches of 25 keep it in sittings.
- **Generator agreement may be low.** If a generator's labels disagree with mine often, more items become `edited`
  and the "who wrote the data" breakdown measures my labels more than theirs. The agreement rate in the README
  makes this visible.
- **Public test set.** The repository and the `/evals` pages publish every test transcript, so future models may
  train on them. That's acceptable for a portfolio project, and the pages carry `noindex`; a set meant to stay
  held out for years would need to be private.
- **Two-stage saving won't show on eval data.** Almost every eval item has a flagged turn. The escalation rate,
  not the eval-set cost, is the number to judge it by.
- **Opus output tokens are unmeasured.** The cost table's high estimate assumes Opus writes four times Haiku's
  output; the `dev` run checks that before the `test` run.
- **Audio alignment.** A transcription that merges or splits turns can misattribute a span. The alignment counts
  turn mismatches so they are visible rather than silently scored as errors.

## Decisions (2026-10-23)

- Every human recording has two different speakers.
- The non-Claude generators are Gemini, DeepSeek, Grok and GPT, 30 test items each, plus 30 hand-written.
- Sonnet is a fourth configuration.
- The gate covers both the default model (Opus) and the deployed demo model (Haiku).
- The design is accepted and recorded as ADRs 0008–0013.
