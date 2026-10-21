# Commitment Tracker AI — Part 1 Kickoff Brief

Oct 21, 2026 · Glenn McDonald

Paste this into Claude Code to start Part 1. Part 1 delivers text in, validated commitment labels out, plus a local evaluation harness. There is no audio, UI or deployment in Part 1.

## Context

Commitment Tracker AI extracts commitments from conversation transcripts: who promised what, to whom, and by when. It sorts each span into one of eight labels. The project is a portfolio piece, so code quality, tests and measured accuracy matter more than features. The backend, extractor and evaluation are Python; the Part 2 frontend will be Next.js, consuming the API's OpenAPI schema. Use test-driven development, as in FlakeHunter.

The project repo is `glennmcd/commitment-tracker-ai` (github.com/glennmcd/commitment-tracker-ai). Build everything in this brief there.

## Repository layout

- `backend/src/commitment_tracker/schemas.py` holds the Pydantic v2 models shared by the API, extractor and evaluation.
- `backend/src/commitment_tracker/extractor/` holds the prompt, the model adapter, validation with retry, and the date resolver.
- `backend/src/commitment_tracker/api/` is a FastAPI app exposing `POST /analyze`.
- `backend/eval/` holds the dataset (JSONL), the runner and the reports.
- `frontend/` is reserved for the Part 2 Next.js app; leave it empty in Part 1.
- Use Python 3.12+, uv for dependencies and environments, pytest, Ruff for linting and formatting, and mypy in strict mode.

## Schema (schemas.py)

The labels are COMMITMENT, HEDGED, CONDITIONAL, SUGGESTION, REQUEST, REPORTED, REFUSAL and NONE. The first three are ledger labels; HEDGED is stored with a soft flag.

Each classified span returns:

- `label`: one of the eight labels.
- `owner` and `recipient`: speaker ids or names, nullable.
- `action`: a short verb phrase, nullable.
- `due`: an object with `raw` (string or null), `resolved` (ISO date or null) and `precision` (day, week, event, vague or none).
- `condition`: a string or null, required when the label is CONDITIONAL.
- `confidence`: a number from 0 to 1.
- `quote`: exact text from the input.
- `rationale`: one sentence.
- `ambiguous`: a boolean.

The request takes `transcript` (an array of turns, each with a speaker and text), a `call_date` (ISO date) and an optional `timezone`. The response is an array of spans plus metadata: model, latency in milliseconds, token counts and estimated cost in USD.

## Extractor (extractor/)

- Use a model adapter protocol with one implementation on the Anthropic Python SDK. The model id comes from config (pydantic-settings), so evaluation runs can compare models.
- The prompt holds the label definitions, 6–8 few-shot examples and the rule that each span is judged with the preceding turn as context. Prompts live in versioned files such as `prompts/v1.md`.
- The model returns `due.raw` only. A deterministic resolver turns raw phrases ("Friday", "tomorrow", "end of next week", "the 1st") into dates relative to `call_date`. Write the rules yourself with `python-dateutil` for the arithmetic, so every rule is tested.
- Use structured output or tool use for JSON and validate it into the Pydantic models. On failure, retry once with the validation error attached, then raise a typed exception.
- Check that every `quote` is a substring of the input. Drop quotes that aren't and log them as hallucinations.

## API (api/)

- `POST /analyze` validates the request body with the Pydantic models and returns the analysis.
- `GET /health` reports service health.
- Load the API key from the environment and never log transcript text.
- FastAPI generates the OpenAPI schema from the models. Export it to `openapi.json` so the Part 2 frontend can generate a typed client from it.
- Use async handlers so the app can later run on Lambda behind an adapter such as Mangum.

## Evaluation harness (eval/)

- `backend/eval/data/dev.jsonl` holds one item per line: an id, turns, the call date and the expected spans with labels and key fields.
- Seed it with the 24 utterances from the project spec. The remaining development items come in a later task.
- `uv run eval --model <id> --prompt v1` runs the set with bounded async concurrency and caches responses by a hash of the input, the model and the prompt.
- The report covers precision and recall per label, a confusion matrix, ledger F1, field accuracy for owner, action and resolved date, quote-check failures, p50 and p95 latency, and total cost. Use scikit-learn's `classification_report` and `confusion_matrix` for the label metrics.
- Write the report as a JSON file and a markdown summary in `backend/eval/reports/`.

## Tests

- Unit tests for the date resolver cover at least 20 phrases, including week boundaries and month rollover; use `pytest.mark.parametrize`.
- Schema tests cover valid and invalid model outputs.
- Extractor tests use a fake adapter to cover the retry path and the quote check.
- An API test checks `/analyze` with FastAPI's `TestClient` and a fake adapter.

## Done when

- [ ] `uv run pytest` passes with no network calls, and Ruff and mypy are clean.
- [ ] `uv run eval` runs on the 24 seed items and writes a report.
- [ ] `curl` against a local `/analyze` call returns validated spans for a sample transcript.
- [ ] `openapi.json` is exported and committed.
- [ ] The README covers setup, the label definitions and how to run the evaluation.

## Out of scope for Part 1

Audio, transcription, the Next.js frontend, a database, AWS deployment and the MCP server all wait for later parts.

## Working style

**Step 0: shared practices repo.** Before planning, read the FlakeHunter repo (github.com/glennmcd/flakehunter), especially its CLAUDE.md, custom commands, hooks, settings, and testing and commit conventions. Extract everything that isn't FlakeHunter-specific into a new repo, `glennmcd/cc-practices-plugin`, packaged as a Claude Code plugin. FlakeHunter is TypeScript, so make language-specific pieces (hooks that run tests, linters or formatters) configurable per project, and add Python equivalents (pytest, Ruff, mypy). Then install that plugin in this repo, and keep this repo's CLAUDE.md limited to Commitment Tracker AI specifics. List anything you couldn't generalize.

Propose the plan and file tree first, then build in small commits, writing tests before implementation where practical. Ask before adding any dependency outside the stack named here.
