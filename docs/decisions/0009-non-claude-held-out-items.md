# 0009. Held-out items drafted by non-Claude models and reviewed blind

Date: 2026-10-23 · Status: Accepted

## Context

The test set needs 150 labelled items. Writing them all by hand is slow, and drafting them with Claude would
measure the extractor, which is Claude, against data phrased the way Claude reads commitments. Drafts from any
model can carry wrong labels, and a reviewer who sees the generator's label first tends to agree with it.

## Decision

- **Authors.** `test` holds 30 items each from hand-writing, Gemini, DeepSeek, Grok and GPT, and no Claude drafts.
  `dev` grows from 24 to 50 with 10 hand-written items and 16 Claude drafts, since its score is never a headline.
- **Generation.** `backend/eval/generation/prompt-v1.md` is a model-agnostic prompt pasted into each model's chat
  app with its placeholders filled in. Batches are 25 items or fewer, and the call date varies between batches
  (a Monday, a Friday, a month end) to exercise the date resolver. No API keys, SDKs or scripts are added for these
  models. A prompt change is a new version file, and set manifests name the version each batch came from.
- **Import.** `uv run eval import <file> --batch <name> --provenance <generator>` strips Markdown fences, validates
  every line with the dataset rules and reports every rejection with its reason, drops exact duplicates of items
  in any set, flags near-duplicates for review, and writes the rest to `staging/<batch>` as `unreviewed`. It
  recomputes `due_resolved` with the project's resolver and records disagreements for review without overwriting
  the generator's date.
- **Blind review.** `uv run eval review --batch <name>` shows the transcript and asks for my label on each span
  before showing the generator's. Provenance and the generator's note stay hidden until the item is decided.
  Matching labels need one keypress; disagreements show both, and I keep, change or reject the item. A date
  disagreement is settled as a generator mistake or a resolver bug; a resolver bug becomes a failing test.
  `$EDITOR` edits are re-validated on save.
- **Promotion.** `uv run eval promote --batch <name> --to <set>` moves accepted and edited items, keeping their
  provenance. The review log is kept with the batch and gives agreement per generator and per label.
- **Tuning discipline.** Prompts are tuned on `dev` only. A prompt version is committed when final and only then
  run on `test`, and every `test` run is a committed report (ADR 0012).

## Consequences

- **Less self-flattery.** The extractor is scored on phrasing it didn't write, and the provenance breakdown shows
  whether any one family's items are easier.
- **Labels are mine.** Every non-spec item is reviewed by me, so the test set measures agreement with my reading of
  the spec. The published agreement rates show how often the generators differed.
- **Review time.** About 180 items at a minute or two each, in batches of 25.
- **Public data.** Test items are in the repository and on the site, so future models may train on them. That is
  acceptable for this project.

## Alternatives considered

- **Claude drafts in `test`.** Fastest, but biased towards the extractor's own reading.
- **Calling the other models through their APIs.** Automates generation but adds keys, SDKs and spend for a task
  done a handful of times.
- **Review with the generator's label shown.** Faster, but anchors the reviewer and inflates agreement.
