# Commitment Tracker AI — Part 2 Kickoff Brief

Oct 21, 2026 · Glenn McDonald

Paste this into Claude Code to start Part 2. Part 2 turns the Part 1 text API into a live demo at
`commitmentai.g26work.com`: a visitor records up to 60 seconds, plays a canned two-person clip or types text, and
sees the commitments come back. It adds transcription, a Next.js frontend, AWS deployment and CI. The product spec is
`docs/spec.md`; Part 1's design is `docs/plans/part-1-extraction-call.md`.

## Where Part 1 left off

- `POST /analyze` takes a text transcript and returns validated spans. The extractor, date resolver, quote check and
  evaluation harness are done and tested, released as v0.2.0.
- `Turn` has a speaker and text but no timestamps, so spans can't point to a moment in the audio yet.
- The only workflow is release-please. There is no CI, deployment or frontend; `frontend/` is empty.

Keep everything Part 1 built working unchanged. `POST /analyze` stays the text-mode endpoint.

## Step 0: design before building

Write `docs/plans/part-2-audio-and-deploy.md`, in the style of the Part 1 extraction-call plan, with sources checked
against current AWS and Next.js documentation. Stop for my approval before writing code. It must settle:

1. **Transcription mode.** Compare Amazon Transcribe batch jobs with streaming transcription for a clip of 60 seconds
   or less: speaker labels, latency, cost and Lambda fit. Recommend one and state the latency you expect.
2. **Request flow.** Lambda behind API Gateway can't hold a request open for transcription plus extraction, so use a
   job resource (below) unless the design finds something better.
3. **Running FastAPI on Lambda.** Mangum or the AWS Lambda Web Adapter, plus how the uv project is packaged (zip
   bundling or a container image).
4. **Infrastructure language.** My default is AWS CDK in TypeScript under `infra/`, so FlakeHunter's constructs for
   rate limiting, SSM secrets, the budget kill switch and Amplify hosting can be reused. Confirm or argue otherwise.
5. **Sample clips.** My default is to generate the canned two-person clips with Amazon Polly, two voices, from
   scripted dialogues, so each clip has a known ground-truth transcript and labels.

Record each accepted decision as an ADR in `docs/decisions/`.

## Backend changes

- **Turn timestamps.** Add optional `start_ms` and `end_ms` to `Turn`. Text mode leaves them null; audio mode fills
  them from the transcription. The frontend shows a span's time through its `turn_index`. This changes the request
  shape, so bump `API_VERSION` and run `uv run export-openapi` in the same commit.
- **Transcriber behind an adapter.** A `Transcriber` protocol with one AWS implementation and a fake for tests,
  mirroring the model adapter. It returns turns with speaker ids and timestamps. Speaker ids (`spk_0`, `spk_1`) map
  to the names the visitor entered, with `Speaker 1` and `Speaker 2` as defaults.
- **Job resource.**
  - `POST /uploads` returns a presigned S3 POST capped by size, so audio never passes through API Gateway.
  - `POST /jobs` starts a job from an upload key or a sample-clip id, with the call date and speaker names.
  - `GET /jobs/{id}` returns the status (`uploaded`, `transcribing`, `analyzing`, `done`, `failed`) and, when done,
    the transcript, the analysis and per-stage latency.
  - Key jobs by a hash of the audio plus the call date and speaker names, so a retried upload returns the existing
    job instead of a duplicate.
- **Job storage.** Keep job state in DynamoDB with a TTL of one hour. PostgreSQL waits for Part 4. A transcript lives
  only in its job record until the TTL removes it.
- **Audio is transient.** Delete the S3 object as soon as transcription finishes, and back that up with a one-day
  lifecycle rule on the bucket.
- **Duration cap.** Enforce the 60-second limit on the server as well as in the browser, and reject longer clips with
  a clear error code.
- **Feedback.** `POST /feedback` takes a thumbs-up or thumbs-down per span. It stores the transcript and labels only
  when the visitor ticks the consent box; otherwise it stores the vote, label and job id alone.
- **Guardrails.** Per-client rate limiting and a daily budget kill switch, adapted from FlakeHunter. The Anthropic API
  key comes from SSM.
- The Part 1 rules still apply: never log transcript text or quotes, keep the import layering test passing, and give
  new modules (`transcription/`, `jobs/`) layering rules in `tests/test_layout.py`.

## Frontend (frontend/)

- Next.js with the App Router and strict TypeScript, generating a typed client from `openapi.json` (openapi-typescript
  and openapi-fetch). A CI step fails when the generated client is stale.
- Three ways in: record (MediaRecorder, with a 60-second countdown that stops itself), choose a sample clip, or type
  or paste text.
- A consent notice before the microphone is used. Fields for the call date and speaker names.
- A status line that follows the job stages: uploading, transcribing, analyzing.
- Results: the transcript with each span highlighted by label, a card per ledger commitment (owner, recipient,
  action, due words and resolved date, confidence, quote and timestamp, with HEDGED marked soft and the condition
  shown for CONDITIONAL), and a **Not a commitment** panel listing near misses with their rationale.
- Prompt chips that invite visitors to try to trick it ("Try a hedge," "Try sarcasm") and fill text mode with an
  example.
- Thumbs-up and thumbs-down on each span, with the consent tickbox.
- Accessible: usable by keyboard, labels are not told apart by colour alone, and the layout works on a phone.
- Tests: component tests with Vitest and Testing Library, plus one Playwright test of text mode against a mocked API.

## Infrastructure (infra/)

- The API on Lambda behind API Gateway, the S3 audio bucket, the DynamoDB tables (jobs, rate limits, feedback),
  Transcribe permissions scoped to the bucket, SSM parameters, the budget kill switch and alarms.
- The frontend on Amplify at `commitmentai.g26work.com`, with CORS on the API limited to that origin and localhost.
- Least-privilege IAM, with a test that each role's policy is scoped as intended. Stacks synthesize with no AWS
  credentials, so CI can check them.

## CI and tooling

- Add `.github/workflows/ci.yml`, with actions pinned to commits as in the release-please workflow:
  - Backend: pytest, Ruff, mypy, and the `openapi.json` freshness test.
  - Frontend: lint, typecheck, tests and build.
  - Infra: `cdk synth` and its tests.
- No network calls or AWS access in CI. Deployment from a tag can come later; document the manual deploy command in
  `docs/deploying.md`.
- Add `typescript` to `.claude/cc-practices.json` with the frontend and infra commands, so the plugin's hooks and
  checks cover the new code.
- Ask before adding dependencies outside this brief. The new ones approved here are: boto3 and the Transcribe client
  the design picks, the Lambda adapter it picks, Next.js, React, openapi-typescript, openapi-fetch, Vitest, Testing
  Library, Playwright and the AWS CDK libraries.

## Done when

- [x] The design doc and its ADRs are accepted.
- [ ] `commitmentai.g26work.com` is live: recording, sample clips and text mode all return results.
- [ ] Each job records per-stage latency, and the README states the measured p50 and p95 for a sample clip against
      the 10-second target, whether or not it's met.
- [ ] Audio is gone from S3 after transcription, and a test or script proves it.
- [ ] Rate limiting and the budget kill switch work, verified by a test or a documented manual check.
- [ ] CI runs on every push and is green, and `openapi.json` and the frontend client are in sync.
- [ ] The README covers the demo, architecture, deployment and costs, with a screenshot of the results view.

## Out of scope for Part 2

The 150-item held-out test set, audio evaluation items, the model comparison and the evaluation gate in CI wait for
Part 3. The PostgreSQL ledger, the follow-up matcher and the MCP server wait for Parts 4–5.

## Working style

Same as Part 1: plan and file tree first, then small Conventional Commits with tests before implementation where
practical. Use `feat:` only for visible changes to the demo or API. Never bump `__version__` by hand; bump
`API_VERSION` only when the request or response shape changes.
