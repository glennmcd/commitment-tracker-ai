# CLAUDE.md

Commitment Tracker AI extracts commitments from conversation transcripts: who promised what, to whom, and by when.
Each span gets one of eight labels; COMMITMENT, HEDGED and CONDITIONAL are ledger labels. The full product spec,
label table and the 24 seed utterances are in `docs/spec.md`; the current build brief is `docs/part-3-brief.md`,
and its design is `docs/plans/part-3-evaluation.md`.

Shared practices (TDD loop, Conventional Commits, secrets, Python tooling) come from the local `cc-practices`
plugin, configured in `.claude/cc-practices.json`. This file covers only what is specific to this project.

## Layout

- `backend/`: the Python project (its own `pyproject.toml` and `uv.lock`); packages under
  `src/commitment_tracker/`, tests in `tests/`, evaluation sets and reports in `eval/`.
- `frontend/`: the Next.js 16 demo site, a static export with no server code. A bun workspace with `infra/`.
- `infra/`: AWS CDK in TypeScript. The owner deploys (`docs/deploying.md`).
- `docs/`: `plans/` (accepted designs), `decisions/` (ADRs), `evaluation.md`, `releasing.md`.
- Generated and committed, never edited by hand: `openapi.json` (`uv run export-openapi`),
  `frontend/src/api/schema.d.ts` (`bun run gen:api`) and `frontend/src/data/evals/` (`uv run eval-export-site`).

`docs/code-map.md` lists every package and directory; read it to find where a change belongs.

## Commands

Run from `backend/`:

```bash
uv sync
uv run pytest                       # no network calls
uv run ruff check . && uv run ruff format --check .
uv run mypy                         # strict
uv run eval-gate                    # CI's regression gate
```

The other `eval` commands are in `docs/evaluation.md`; `uv run eval` without `--offline` spends money on cache
misses.

Run from `frontend/` (the root's `bun run lint`, `typecheck` and `test` cover `frontend/` and `infra/` together):

```bash
bun install
bun run dev
bun run test                        # Vitest, no network calls
bun run typecheck
bun run gen:api                     # after `uv run export-openapi`; commit the result
bun run e2e                         # builds with a fake API address, then runs Playwright against out/
```

## Rules for this project

- **Import layering** (enforced by `tests/test_layout.py`): `schemas` and `guardrails` import no other first-party
  module; `extractor`, `jobs` and `feedback` import neither `api` nor `evaluation`; `transcription` imports
  neither `extractor`, `jobs`, `api` nor `evaluation`; `evaluation` uses the extractor, never the API.
- **The model only proposes.** Output is validated into the Pydantic models (one retry with the validation error,
  then a typed exception), every `quote` must be a substring of the input (others are dropped and logged as
  hallucinations), and `due.resolved` is computed by the deterministic resolver from `call_date`, never by the model.
- **Model behind an adapter.** The Anthropic SDK lives in one adapter; tests use a fake adapter. The model id comes
  from settings (pydantic-settings) so evaluation runs can compare models.
- **Never log transcript text** or quotes. Log ids, counts, labels, latency and token usage only. The API key comes
  from the environment.
- **Prompts are versioned files.** Change a prompt by adding a new version; evaluation reports name the prompt and
  model they used. Tune prompts on development data only.
- **Ask before adding a dependency** outside the approved stack, listed in
  `docs/code-map.md`.
- **Never bump versions by hand.** release-please owns `commitment_tracker.__version__` and
  `.release-please-manifest.json`. The API contract version (`API_VERSION` in `api/app.py`) is separate: bump it
  only when the request or response shape changes, then run `uv run export-openapi`.
