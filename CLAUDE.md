# CLAUDE.md

Commitment Tracker AI extracts commitments from conversation transcripts: who promised what, to whom, and by when.
Each span gets one of eight labels; COMMITMENT, HEDGED and CONDITIONAL are ledger labels. The full product spec,
label table and the 24 seed utterances are in `docs/spec.md`; the current build brief is `docs/part-1-brief.md`.

Shared practices (TDD loop, Conventional Commits, secrets, Python tooling) come from the local `cc-practices`
plugin, configured in `.claude/cc-practices.json`. This file covers only what is specific to this project.

## Layout

- `backend/`: the Python project (its own `pyproject.toml` and `uv.lock`).
  - `src/commitment_tracker/schemas.py`: Pydantic v2 models shared by the API, extractor and evaluation.
  - `src/commitment_tracker/extractor/`: prompt files (`prompts/v1.md`, ...), the model adapter, validation with
    one retry, the quote check and the date resolver.
  - `src/commitment_tracker/api/`: FastAPI app (`POST /analyze`, `GET /health`).
  - `src/commitment_tracker/evaluation/`: the eval runner, importable so `uv run eval` works.
  - `eval/`: `data/dev.jsonl` and `reports/` (committed); `.cache/` holds cached model responses (ignored).
  - `tests/test_layout.py`: enforces the import layering below.
- `docs/plans/`: build plans; `part-1-extraction-call.md` is the accepted design for the model call.
- `frontend/`: reserved for the Part 2 Next.js app; empty in Part 1.
- `openapi.json`: exported from FastAPI and committed; the frontend generates its client from it.

## Commands

Run from `backend/`:

```bash
uv sync
uv run pytest                       # no network calls
uv run ruff check . && uv run ruff format --check .
uv run mypy                         # strict
uv run eval --model <id> --prompt v1
```

## Rules for this project

- **Import layering** (enforced by `tests/test_layout.py`): `schemas` imports no other first-party module;
  `extractor` imports neither `api` nor `evaluation`; `evaluation` uses the extractor, never the API.
- **The model only proposes.** Output is validated into the Pydantic models (one retry with the validation error,
  then a typed exception), every `quote` must be a substring of the input (others are dropped and logged as
  hallucinations), and `due.resolved` is computed by the deterministic resolver from `call_date`, never by the model.
- **Model behind an adapter.** The Anthropic SDK lives in one adapter; tests use a fake adapter. The model id comes
  from settings (pydantic-settings) so evaluation runs can compare models.
- **Never log transcript text** or quotes. Log ids, counts, labels, latency and token usage only. The API key comes
  from the environment.
- **Prompts are versioned files.** Change a prompt by adding a new version; evaluation reports name the prompt and
  model they used. Tune prompts on development data only.
- **Ask before adding a dependency** outside the stack in `docs/part-1-brief.md` (FastAPI, Pydantic v2,
  pydantic-settings, anthropic, python-dateutil, scikit-learn, pytest, Ruff, mypy).
- Agent commits are allowed here; keep them small and Conventional.
