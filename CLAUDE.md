# CLAUDE.md

Commitment Tracker AI extracts commitments from conversation transcripts: who promised what, to whom, and by when.
Each span gets one of eight labels; COMMITMENT, HEDGED and CONDITIONAL are ledger labels. The full product spec,
label table and the 24 seed utterances are in `docs/spec.md`; the current build brief is `docs/part-3-brief.md`,
and its design is `docs/plans/part-3-evaluation.md`.

Shared practices (TDD loop, Conventional Commits, secrets, Python tooling) come from the local `cc-practices`
plugin, configured in `.claude/cc-practices.json`. This file covers only what is specific to this project.

## Layout

- `backend/`: the Python project (its own `pyproject.toml` and `uv.lock`).
  - `src/commitment_tracker/schemas.py`: Pydantic v2 models shared by the API, extractor and evaluation.
  - `src/commitment_tracker/settings.py`: pydantic-settings configuration (model, limits, AWS resource names).
  - `src/commitment_tracker/extractor/`: prompt files (`prompts/v1.md`, ...), the model adapter, validation with
    one retry, the quote check, the date resolver and pricing.
  - `src/commitment_tracker/transcription/`: the transcriber protocol, the Amazon Transcribe batch adapter, the
    mapping from Transcribe output to timed turns, and a fake.
  - `src/commitment_tracker/jobs/`: the job record and its stores (DynamoDB, memory), presigned uploads, WAV
    checks, sample clips (`samples.json`) and the worker that transcribes, analyzes and deletes the audio.
  - `src/commitment_tracker/feedback/`: span thumbs up or down, with optional consent to keep the transcript.
  - `src/commitment_tracker/guardrails/`: per-client rate limits and the daily spend cap.
  - `src/commitment_tracker/api/`: FastAPI app (`GET /health`, `POST /analyze`, `POST /uploads`, `POST /jobs`,
    `GET /jobs/{job_id}`, `POST /feedback`, `GET /samples`) and `export_openapi.py`.
  - `src/commitment_tracker/lambda_handlers.py`: the Mangum API handler and the worker handler; one zip serves
    both, and the Anthropic key is read from SSM on a cold start.
  - `src/commitment_tracker/evaluation/`: the eval runner, importable so `uv run eval` works.
  - `eval/`: `sets/<name>/` (items and manifest per set) and `reports/<set>/` (committed),
    `generation/prompt-v1.md` (the prompt for drafting items with other models); `.cache/` holds cached model
    responses (ignored). See `docs/plans/part-3-evaluation.md`.
  - `samples/`: the scripted dialogues behind the demo's sample clips and their ground truth.
  - `scripts/`: run by hand with AWS credentials: `make_samples.py` (Polly clips), `measure_latency.py` and
    `check_audio_gone.py` against the deployed stack.
  - `tests/test_layout.py`: enforces the import layering below.
- `docs/plans/`: build plans; `part-1-extraction-call.md` is the accepted design for the model call,
  `part-2-audio-and-deploy.md` for audio and deployment, and `part-3-evaluation.md` for evaluation.
- `docs/decisions/`: numbered ADRs. `docs/releasing.md`: how versions and releases work. `docs/deploying.md`: the
  AWS account, deploy and kill-switch steps, which the owner runs.
- `infra/`: AWS CDK in TypeScript. `lib/api-stack.ts` (bucket, tables, Lambda functions, the Transcribe event rule,
  the budget kill switch; `DEFAULT_DEMO_MODEL`) and `lib/web-stack.ts` (Amplify Hosting), wired in
  `bin/commitment-tracker.ts`. `lambda/` holds the password authorizer and the budget-stop function, `scp/` the
  account guardrail policy, `scripts/bundle-api.ts` the Python zip build, and `test/` synth, IAM and bundle tests.
- `frontend/`: the Next.js 16 demo site, a static export (`next build` writes `out/`, served by Amplify Hosting)
  with no server code. A bun workspace with `infra/`, linted by the root Biome config.
  - `src/app/`: the routes; `page.tsx` is the demo, with `<Demo />` inside `PasswordGate`.
  - `src/components/`: the demo UI (recorder, sample picker, results, feedback, password gate), with Vitest tests
    beside each component.
  - `src/lib/`: plain helpers (job polling, upload, WAV encoding, relabelling, release version), tested alone.
  - `src/api/`: `schema.d.ts` generated from `openapi.json` (never edited by hand) and the typed `client.ts`. The
    API address comes from `NEXT_PUBLIC_API_BASE_URL` at build time.
  - `e2e/`: the Playwright test, served from `out/` by a small static server, with the API intercepted.
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
- **Ask before adding a dependency** outside the stack the briefs approved: Part 1 (FastAPI, Pydantic v2,
  pydantic-settings, anthropic, python-dateutil, scikit-learn, pytest, Ruff, mypy) and Part 2 (boto3, Mangum,
  Next.js, React, openapi-typescript, openapi-fetch, Vitest, Testing Library, Playwright, the AWS CDK libraries).
  Part 3 adds none.
- **Never bump versions by hand.** release-please owns `commitment_tracker.__version__` and
  `.release-please-manifest.json`. The API contract version (`API_VERSION` in `api/app.py`) is separate: bump it
  only when the request or response shape changes, then run `uv run export-openapi`.
