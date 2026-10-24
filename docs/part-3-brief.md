# Commitment Tracker AI — Part 3 Kickoff Brief

Oct 23, 2026 · Glenn McDonald

Paste this into Claude Code to start Part 3. Part 3 turns "it works on 24 examples" into a measured result: several
evaluation sets (including items drafted by non-Claude models), audio evaluation items, a three-way model
comparison, a web page that shows the results, and a regression gate in CI. The product spec is `docs/spec.md` (see
"Evaluation plan"); Part 2's design is `docs/plans/part-2-audio-and-deploy.md`.

## Where Part 2 left off

- The demo is live at `commitmentai.g26work.com` (v0.6.1): recording, Polly sample clips and text mode.
- `uv run eval` runs the extractor over one JSONL file with a response cache, and writes JSON and Markdown reports.
  The JSON report already holds per-item expected and predicted spans.
- `eval/data/dev.jsonl` has 24 items, not the 50 the spec calls for. The only report is Haiku on prompt v1, scoring
  1.000, and that prompt was tuned on the same items, so it shows the pipeline works, not how accurate it is.
- CI runs backend, frontend, e2e and infra checks with no network calls. There is no evaluation job.
- The frontend is a static export behind `PasswordGate`.

Keep all of that working. `uv run eval --data <file>` keeps working alongside the new `--set` option.

## Step 0: design before building

Write `docs/plans/part-3-evaluation.md`, in the style of the earlier plans, and stop for my approval before writing
code. It must settle:

1. **Evaluation-set layout.** The directory and manifest format below, how existing reports and `dev.jsonl` migrate,
   and how a report pins the exact version of the set it ran on.
2. **Authoring and labeling.** The mix of hand-written items, items drafted by other model families from
   `eval/generation/prompt-v1.md`, and any Claude drafts; how blind review works; and how the test sets stay out of
   prompt tuning. The extractor is Claude, so the plan should favour non-Claude drafts for held-out sets.
3. **Audio items.** How the 30 audio test items are made. Polly gives clean audio and a known transcript but will
   understate the transcription penalty; compare it with my own recordings or a mix, and recommend one.
4. **Two-stage pipeline.** How "small model screens, large model extracts flagged spans" fits behind the existing
   adapter and extractor without breaking the import layering, and how its cost and latency are reported as one run.
5. **The regression gate (stubbed, see below).** Confirm the report-required design or argue for something better
   that still spends nothing in CI.
6. **The evaluation pages.** Routes, where their data comes from, and how it stays in sync with the reports.
7. **Run cost.** Estimate the cost of one full run per configuration per set from the existing Haiku report's
   per-item cost and the prices in `extractor/pricing.py`, so I know what the comparison costs before I run it.

Record accepted decisions as ADRs in `docs/decisions/`.

## Evaluation sets

- Each set lives in `eval/sets/<name>/`: `items.jsonl` plus `set.json`, a manifest with the name, a one-line
  description, a role (`dev`, `test` or `staging`), whether it is gated, and where its items came from.
- Starting sets:
  - `dev`: today's 24 items moved here, grown to 50. The only set prompts may be tuned on.
  - `test`: 150 held-out items, built up from reviewed batches, the headline set.
  - `audio`: the 30 audio items, a manifest mapping each to a `test` item id, with the audio stored outside git
    (state where in the design) and a script that regenerates or fetches it.
  - `staging/<batch>`: imported drafts awaiting review. Never scored in headlines or gated.
- Items gain `provenance` (`spec`, `hand-written`, `gemini-<model>`, `deepseek-<model>`, `claude-<model>`, …) and
  `review` (`unreviewed`, `accepted`, `edited`). Add them to `EvalItem`; `extra="forbid"` stays.
- `uv run eval --set <name>` runs a set; `uv run eval-sets` lists sets with item counts, review status and label mix.
- Reports record the set name and a hash of its `items.jsonl`, and break scores down by provenance, so the README
  can show whether results depend on who wrote the data.
- A test fails if any item's transcript appears in more than one set (except `audio`, which points at `test` by id),
  or if any non-dev item's text appears in a prompt file.

## Generating items with other models

- `eval/generation/prompt-v1.md` is a model-agnostic prompt (already written; review it in Step 0). I paste it into
  Gemini, DeepSeek or another chat model, with the placeholders filled in, and save each reply as a JSONL file.
  Batches are 25 items or fewer. No API keys, SDKs or scripts for these models are added.
- `uv run eval import <file> --batch <name> --provenance <generator>` validates every line with the existing dataset
  rules, reports rejected lines with reasons rather than stopping at the first, drops duplicates of items in any
  set, and writes the rest to `staging/<batch>` as `unreviewed`.
- The import recomputes `due_resolved` with the project's date resolver and marks any disagreement with the
  generator for review. It does not overwrite the generator's date: a disagreement is either a generator mistake or
  a resolver bug, and I decide which.
- Change the generation prompt by adding a new version, as with extractor prompts. Reports name the prompt version
  their items came from (via the set manifest).

## Review

- `uv run eval review --batch <name>`: a terminal walk through unreviewed items. It shows the transcript first and
  asks me for each span's label before revealing the generator's. Matching labels need one keypress to accept;
  disagreements show both, with the generator's note, and I keep, change or reject the item. Field edits open the
  item in `$EDITOR` and are re-validated on save.
- `uv run eval promote --batch <name> --to test` moves accepted and edited items into a set, keeping provenance.
  Promoting into a gated set changes its hash, so the gate asks for a new baseline (below).
- The review log (agreement rate between me and each generator, per label) is saved with the batch. It's a useful
  number for the README.

## Model comparison

- Configurations: Haiku, Opus (the default model), and the two-stage setup. Add Sonnet only if the design argues for
  it.
- I run the comparison myself, locally, with `uv run eval --set test` per configuration. Claude Code builds and
  tests the code but does not run paid evaluations.
- `uv run eval-compare --set <name>` reads that set's latest report per configuration and writes the README results
  table: ledger F1, field accuracy, cost per clip and p95 latency.
- The audio penalty compares ledger F1 on the `audio` set, transcribed, against the same items as text. It runs
  Transcribe, so it is also a manual, local run.

## Regression gate (stubbed)

The gate must not spend money in CI. Build the parts that cost nothing; leave the paid run as a clearly marked stub.

**Build fully:**

- `eval/baseline.json`: per gated set, the accepted scores (ledger F1, field accuracy, failed items) with the model,
  prompt version, prompt hash and set hash they came from. Updating it is a deliberate commit.
- `uv run eval-gate`: a pure comparison of committed reports against the baseline for every gated set. It fails if
  ledger F1 drops by more than 0.02, if any item failed, or if the set hash differs from the baseline's (the set
  changed, so re-baseline on purpose). It prints field-accuracy changes as warnings. Unit-test the comparison
  thoroughly, including the boundary at exactly 0.02.
- **Report-required check.** The gate also fails when the current prompt hash, default model and set hash have no
  matching committed report. So a prompt, model or test-set change can't merge until someone has run the
  evaluation locally and committed its report. CI verifies; it never runs the model.
- `uv run eval --offline`: reads only from the response cache and fails on a miss, so a run is guaranteed to spend
  nothing.
- A CI job `eval-gate` that runs only when prompts, the default model setting, the evaluation code, `eval/sets/` or
  `eval/baseline.json` change. It needs no secrets.

**Stub only:**

- A live evaluation job in `ci.yml`, triggered only by `workflow_dispatch` and disabled with `if: false`. Its steps
  are written out and commented, with a note listing what enabling it would need: an Anthropic key in a protected
  environment, a spend cap, cache restore between runs, and the cost estimate from Step 0.
- No Anthropic key is added to the repository, and no workflow calls the API.

## Evaluation pages (frontend/)

- A read-only `/evals` section of the existing Next.js site, built statically from committed reports and set files.
  It calls no API, so it sits outside `PasswordGate`: hiring managers can open it without the demo password.
- `uv run eval-export-site` writes the data the pages need (scores, per-item results joined with transcripts, set
  manifests) as JSON under `frontend/`. The output is committed, and CI fails when it is stale, as it already does
  for the generated API client.
- Pages:
  - **Overview:** the results table per set, and a list of sets with role, item count, review status, label mix and
    provenance mix.
  - **Run:** headline scores, per-label table, confusion matrix, field accuracy, scores by provenance, failed items,
    and the run's model, prompt, set hash, cost and latency.
  - **Items:** filter by label, tag, provenance and right or wrong. Each item shows its transcript with the expected
    and predicted spans side by side, mismatched fields marked, plus dropped quotes and errors.
  - **Compare:** two runs on the same set: score changes, and the items that went from right to wrong and back.
- The confusion matrix is a real table with the numbers always shown; shading is a supplement. Same accessibility
  rules as the demo: keyboard use, nothing told apart by colour alone, works on a phone.
- Link the pages from the demo and the README.
- Tests: Vitest component tests against fixture reports, and one Playwright test that opens a run and an item.
- No new frontend dependencies unless I approve one; plain CSS should be enough for the matrix and bars.

## Presentation

- README: the results table, the audio penalty, scores by provenance, the review agreement rates, and a short
  failure analysis drawn from the confusion matrix and the worst test items. Replace the dev-set perfect score with
  the test-set numbers, whatever they are.
- `docs/evaluation.md`: the sets and their roles, how items are generated, imported, reviewed and promoted, how to
  run each evaluation and what it costs, and how to update the baseline.

## Done when

- [ ] The design doc and its ADRs are accepted.
- [ ] Sets live under `eval/sets/`; `dev` has 50 items and `test` 150, every non-spec item reviewed by me, and the
      leak test passes.
- [ ] At least one batch each from Gemini and DeepSeek has gone through import, blind review and promotion.
- [ ] The 30 audio items exist and can be regenerated or fetched by script.
- [ ] `eval-compare` produces the results table; I have run the three configurations on `test` and committed their
      reports.
- [ ] `eval-gate` and the report-required check are tested and run in CI with no secrets; the live job is present
      but disabled.
- [ ] `/evals` is live outside the password gate, its data is in sync with the reports, and its tests pass in CI.
- [ ] The README shows test-set results, the audio penalty, scores by provenance and the failure analysis.

## Out of scope for Part 3

Running paid evaluations from CI, calling Gemini or DeepSeek through their APIs, and editing items through the web
pages (they are read-only). The PostgreSQL ledger, the follow-up matcher and the MCP server wait for Parts 4–5.

## Working style

Same as before: plan and file tree first, then small Conventional Commits with tests before implementation where
practical. Use `feat:` for the evaluation pages, since they are visible on the site, and for new commands. Ask
before adding dependencies. Never bump `__version__` by hand; this part doesn't change the analyze API's shape, so
`API_VERSION` should not move.
