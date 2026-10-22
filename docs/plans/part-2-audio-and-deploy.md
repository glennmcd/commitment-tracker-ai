# Part 2: audio, the demo and deployment

Oct 21, 2026 · Accepted

How Part 2 turns the text API into a live demo at `commitmentai.g26work.com`. A visitor records up to 60 seconds,
picks a sample clip or types text. The audio is transcribed into timed turns, and the turns go through the Part 1
extractor unchanged. This document settles the five design questions in `docs/part-2-brief.md`, then lays out the
backend, frontend, infrastructure and CI work as a file tree and a commit sequence.

Sources were checked on 2026-10-21 against docs.aws.amazon.com, aws.amazon.com, nextjs.org and docs.astral.sh. They
are listed at the end with the section each claim comes from. Where a source is anecdotal or a page did not load,
the text says so, and the measurement step confirms the claim against the real service.

## Summary

| Decision | Choice |
| --- | --- |
| Transcription mode | Amazon Transcribe **batch** jobs with speaker labels, from a 16 kHz mono WAV in our bucket. The finished-job event drives the rest of the pipeline |
| Expected latency (sample clip, 60 s) | Transcription **measured at 15.4 s p50, 15.8 s p95**; about 17–19 s from submit to results with Haiku. That **misses the 10 s target**; the README reports the deployed number |
| Request flow | `POST /uploads` (presigned S3 POST) → `POST /jobs` → Transcribe → EventBridge → worker Lambda → `GET /jobs/{id}` polled by the browser |
| FastAPI on Lambda | **Mangum**, in-process. One zip serves the API handler and the worker handler |
| Packaging | **Zip** for arm64 and Python 3.12, built with `uv export` and `uv pip install --target`. scikit-learn moves to an `eval` dependency group so it stays out of the bundle |
| Infrastructure | **AWS CDK in TypeScript** under `infra/`, adapted from FlakeHunter's stacks and tests |
| Frontend hosting | Next.js 16 as a **static export** on Amplify Hosting; the browser calls the API directly |
| Sample clips | **Amazon Polly** standard voices in us-east-2, two voices, 16 kHz PCM written as WAV with the standard library; dialogues and labels are committed as ground truth |
| AWS account | A **new member account** for this project, with its own guardrail SCP, budget and hosted zone for `commitmentai.g26work.com` |
| Demo model | `claude-haiku-5-5` on the deployed stack; the settings default stays `claude-opus-5-5` |
| Budget | A **$5 daily** spend cap enforced by the API (Claude and Transcribe costs), backed by a **$30 monthly** AWS budget kill switch |

## 1. Transcription mode

| | Batch (`StartTranscriptionJob`) | Streaming (`StartStreamTranscription`) |
| --- | --- | --- |
| Speaker labels | `ShowSpeakerLabels` with `MaxSpeakerLabels: 2`; labels `spk_0`, `spk_1` per item | `ShowSpeakerLabel`; the streaming diarization page limits it to en-US |
| Input | A file in S3: WAV, FLAC, MP3, MP4, Ogg, WebM and others | Raw PCM (not WAV), FLAC or Ogg Opus, sent in 50–200 ms chunks |
| Pacing | None: the service reads the whole file | AWS asks for a stream "as close to real-time as possible", so a 60 s file takes about 60 s to send |
| Latency for 60 s | No documented figure; one re:Post report measured 20–25 s for a 1-minute file | At least the clip's length when paced; sending faster than real time is undocumented |
| Python client | boto3 (GA) | `aws-sdk-transcribe-streaming` (marked experimental, "do not use for production") or `amazon-transcribe` (described as early alpha) |
| Lambda fit | Start the job and return; Transcribe emits a `Transcribe Job State Change` event when it finishes | A Lambda stays open for the whole stream, on an async HTTP/2 client with awscrt |
| Cost | Billed per second, no minimum; the pricing page's example uses $0.006/min | Same billing; the example uses $0.01/min |

**Recommendation: batch.** Streaming pays off only when audio is transcribed *while* it is being spoken. On the
server we hold a finished file, and pacing it in real time makes streaming slower than batch for the same clip. The
only GA Python client is boto3, which has no streaming support.

**Measured latency.** The latency test on 2026-10-21, in us-east-2, ran 10 batch jobs one after another on a
59.0 s two-voice clip with speaker labels:

| | p50 | p95 | Range |
| --- | --- | --- | --- |
| Queue (`StartTime` − `CreationTime`) | 0.0 s | 0.0 s | 0.0 s |
| Processing (`CompletionTime` − `StartTime`) | 15.4 s | 15.8 s | 15.1–15.8 s |
| Wall clock, start call to `COMPLETED` (polled every 1 s) | 16.3 s | 16.9 s | 15.6–16.9 s |

Processing is steady, at about a quarter of the clip's length, with no queueing. All 11 turns came back with the
right speaker, and every turn boundary was within 0.65 s of the truth. Extraction adds another 1.5–3 s on Haiku 5.5
(the Part 1 eval measured a 1.5 s p50 and a 2.6 s p95). The event delivery, the S3 reads and the browser's polling
add a little more. That puts the expected total at about 17–19 s from submit to results, which misses the brief's
10 s target. `measure_latency.py` measures the deployed path (see [Measuring latency](#measuring-latency)), and
the README states the result.

**What would meet 10 s.** The recording would have to be transcribed live: the browser streams PCM to Transcribe
while the visitor speaks, so the transcript is ready about a second after they stop. That needs a relay the
server controls (an API Gateway WebSocket API or similar), because a presigned Transcribe URL handed to the
browser can't enforce the 60 s cap. Sample clips would also have to stream while they play. The `Transcriber`
protocol leaves room for this, but it doubles the transcription work, so I suggest it as a later step if the
measured number is unacceptable.

Two details keep the audio transient:

- The job writes its JSON output to our bucket (`OutputBucketName`, prefix `transcripts/`), not to the
  service-managed location, which keeps results for 90 days.
- After reading the output, the worker deletes the audio object and the transcript object, and calls
  `DeleteTranscriptionJob`.

## 2. Request flow

```text
browser                     API Lambda (Mangum)               AWS                         worker Lambda
───────                     ───────────────────               ───                         ─────────────
record → WAV (16 kHz mono)
POST /uploads ────────────► presigned POST, key uploads/<uuid>.wav, size cap
POST to S3 (direct) ───────────────────────────────────────► S3 uploads/
POST /jobs {upload_id | sample_id, call_date, speaker_names}
                            read object (≤ 1.92 MB), check WAV header and duration
                            job_id = sha256(audio_sha256, call_date, names)
                            put job if absent (else return existing job)
                            StartTranscriptionJob ─────────► Transcribe
◄── 202 {job_id, status: transcribing}
GET /jobs/{id} every 1 s ─► read DynamoDB
                                                              Transcribe Job State Change
                                                              (EventBridge rule) ───────► status analyzing
                                                                                          read transcripts/<id>.json
                                                                                          delete audio, output, job
                                                                                          items → timed turns
                                                                                          Extractor.analyze
                                                                                          status done + latencies
◄── {status: done, transcript, analysis, latency_ms}
```

- **Recording format.** MediaRecorder produces WebM/Opus in Chrome and Firefox and MP4/AAC in Safari. The browser
  decodes the recording with `AudioContext.decodeAudioData`, resamples it to 16 kHz mono with an
  `OfflineAudioContext`, and writes a 44-byte-header PCM WAV. This needs no library. The server then accepts one
  format, reads the duration from the header with the standard library's `wave` module, and the byte cap of the
  presigned POST (60 s × 32,000 B/s + 44 B = 1,920,044 B) doubles as a duration cap. The server checks the header
  as well. A longer or malformed clip gets 422 `audio_too_long` or `audio_invalid`, and its object is deleted.
- **Deduplication.** The job id is a hash of the audio, the call date and the speaker names. A retried upload of
  the same audio returns the existing job, and the duplicate object is deleted. Anyone who already has the audio
  and guesses the call date and names could read the job, which only exposes a transcript of audio they already
  hold.
- **Sample clips** live under `samples/` in the same bucket, deployed from the repo by CDK. Their hashes are in a
  manifest bundled with the API. A sample job skips the upload, and the worker never deletes from `samples/`.
- **Stage latency.** The job record stores timestamps for created, transcription started, the Transcribe event
  received, analysis started and done. `GET /jobs/{id}` returns them as `upload_ms` (for an upload, from presign
  to job), `transcribe_ms`, `analyze_ms` and `total_ms`.
- **Failures** set `status: failed` with the Part 1 error codes (`model_unavailable`, `model_output_invalid`,
  `model_refused`) or `transcription_failed`. The worker's async invoke gets one retry, and it is idempotent: it
  acts only when the job's status is `transcribing` (a conditional update).
- **Text mode.** `POST /analyze` stays unchanged for API clients and curl. The *frontend* sends text through
  `POST /jobs` with a `transcript` source: the API invokes the worker directly, and the worker skips
  transcription. One status line and one feedback path cover all three modes. Feedback copies only what the
  server produced, and no frontend request waits on the HTTP API's 30-second integration timeout. The cost is
  about 0.5–1 s of invocation and polling overhead on text results.

## 3. Running FastAPI on Lambda

**Mangum** wraps the ASGI app in a plain handler (`handler = Mangum(app)`):

- The same zip has a second, ordinary handler for the worker (`jobs.worker.handle`), with no HTTP layer.
- Tests can call the handler offline with a recorded API Gateway v2 event.
- The client IP for rate limiting comes from `scope["aws.event"]["requestContext"]["http"]["sourceIp"]`, which
  API Gateway sets. `X-Forwarded-For` is never trusted.
- Mangum shipped 0.20.0 in December 2025 and 0.21.0 in February 2026, after a gap of more than a year, so it is
  maintained but slow-moving. The adapter is about 1,000 lines with no dependencies. If it stalls, swapping it is
  a one-file change.

**AWS Lambda Web Adapter**, the alternative, runs uvicorn unchanged behind a Lambda layer and adds response
streaming. We don't stream responses, though. Non-HTTP events, such as the EventBridge trigger, arrive as a POST
to `/events`, which would put the worker behind an HTTP route. It also adds a per-Region layer ARN to track.

**Packaging: a zip archive, arm64, Python 3.12** (`backend/.python-version`). The uv Lambda guide's recipe, which
the bundle script runs:

```bash
uv export --frozen --no-dev --no-group eval --no-editable --no-emit-project -o requirements.txt
uv pip install -r requirements.txt --target dist/api --python-platform aarch64-manylinux2014 \
  --python-version 3.12 --only-binary :all: --no-installer-metadata --no-compile-bytecode
cp -r src/commitment_tracker dist/api/
```

Zip archives are limited to 250 MB unzipped. scikit-learn, with NumPy and SciPy, would take most of that, and
only `evaluation/` uses it. scikit-learn therefore moves from `[project.dependencies]` to an `eval` dependency
group, listed in `[tool.uv] default-groups` so that `uv sync` and `uv run eval` behave as they do now. The layering
test already keeps the API and the worker from importing `evaluation`. I rejected a container image: zip is
enough once scikit-learn is out, and an image would add ECR plus a Docker build to every deploy.

**Settings on Lambda.** At cold start the handler reads `ANTHROPIC_API_KEY` from SSM Parameter Store
(SecureString, `/commitment-tracker/prod/ANTHROPIC_API_KEY`) into the settings object, never into the environment
or a log. The table names, bucket name and limits come from Lambda environment variables set by CDK.

## 4. Infrastructure language

**Confirmed: AWS CDK in TypeScript under `infra/`.** The stacks a project like this needs already exist in
FlakeHunter, with tests that synthesize offline:

| FlakeHunter piece | Reused as |
| --- | --- |
| `ApiStack`: HTTP API, `$default` stage throttle, access logs, Lambda with a dedicated log group | The same shape for a Python 3.12 arm64 function |
| SSM read scoped to named parameters, and the `SECRET_NAMES` test | One parameter, `ANTHROPIC_API_KEY` |
| DynamoDB fixed-window rate limit table and its `ADD hits 1` counter | The guardrails table; the limiter is ported to Python |
| Budget kill switch: `CfnBudget` → SNS → `budget-stop` Lambda that sets reserved concurrency to 0 | The same, stopping both the API and the worker functions |
| `WebStack`: Amplify app, branch, custom domain with validation, SSR log role | Amplify app for a static build; domain `commitmentai.g26work.com` |
| `bundle-api.ts` run from `cdk.json`'s `build`; tests with a fixture code path; `synth-worker.ts` | A bundle script that runs the uv commands above; the same test harness |

Writing the CDK app in Python would keep the repo to one language, but it would mean rewriting these constructs and
their tests. The frontend already brings TypeScript into the repo. Infra uses Bun for installs and tests, like
FlakeHunter, and Node for `cdk synth` itself.

New resources beyond FlakeHunter:

- **The audio bucket.** Block public access, SSE-S3, `enforceSSL`, and CORS allowing POST from the site and
  localhost. A one-day expiration lifecycle rule covers `uploads/` and `transcripts/`, but not `samples/`.
- **Three tables**, all on-demand:
  - `jobs`, with a TTL of one hour
  - `guardrails`, holding the rate limit counters and the daily spend items, all with TTLs
  - `feedback`, with votes kept indefinitely and consented transcripts deleted after 90 days by TTL
- **An EventBridge rule** matching `aws.transcribe` / `Transcribe Job State Change` for `COMPLETED` or `FAILED`
  and job names starting `ct-`. Its target is the worker Lambda.
- **IAM, least privilege**, with a test per statement:
  - The API role:
    - `s3:GetObject` and `s3:DeleteObject` on `uploads/*`
    - `s3:GetObject` on `samples/*`
    - `transcribe:StartTranscriptionJob`
    - `s3:PutObject` on `transcripts/*`, which Transcribe needs under the caller's credentials
    - `dynamodb:GetItem`, `PutItem` and `UpdateItem` on `jobs` and `guardrails`
    - `dynamodb:PutItem` on `feedback`
    - `lambda:InvokeFunction` on the worker, for text jobs
    - `ssm:GetParameters` on the one parameter
  - The worker role:
    - `s3:GetObject` and `s3:DeleteObject` on `uploads/*` and `transcripts/*`
    - `transcribe:DeleteTranscriptionJob`
    - `dynamodb:GetItem` and `UpdateItem` on `jobs`
    - `dynamodb:UpdateItem` on `guardrails`
    - `ssm:GetParameters`

  Transcribe's job-level actions can't be scoped to a resource ARN. Where that is so, the test asserts the action
  list exactly instead.
- **CORS on the HTTP API**, limited to `https://commitmentai.g26work.com` and `http://localhost:3000`.
- **Alarms** on the worker's errors, on the API's 5xx rate, and on the daily spend reaching 80% of the cap (a
  custom metric). All three notify the budget email.

**Account: a new member account** in the organization, holding only this project. FlakeHunter's guardrails
don't apply to it, its quotas and concurrency are its own, and its budget kill switch can stop nothing but this
app. Because the account holds one project, the budget can stay account-wide, exactly as in FlakeHunter. The
account setup comes before any AWS work, including the latency test, and `docs/deploying.md` lists each step. You
run them; nothing here is created by CDK.

1. **Create the account.** Create the member account in the organization, set up an SSO permission set and a CLI
   profile for it, and turn on budget alerts.
2. **Write the guardrail SCP.** `infra/scp/commitment-tracker-guardrails.json` adapts FlakeHunter's: the account
   is locked to us-east-2, and the service allow-list adds `transcribe:*`, `events:*` and `polly:*` to the services
   the stacks use. `polly:*` can be removed once the sample clips exist. It is attached from the management
   account.
3. **Bootstrap CDK.** Run `cdk bootstrap` in us-east-2.
4. **Delegate DNS.** Create a hosted zone for `commitmentai.g26work.com` in the new account. Add its four NS
   records to the `g26work.com` zone in the g26work account. Amplify then writes its certificate and domain
   records into the delegated zone itself.
5. **Store the API key.** Create the `ANTHROPIC_API_KEY` SecureString parameter.

The agent synthesizes and tests; you run `cdk deploy`, the account setup and the SCP attachment.

## 5. Sample clips

**Confirmed: Amazon Polly, two voices.** `scripts/make_samples.py` reads `backend/samples/dialogues.jsonl`. Each
dialogue lists turns with a speaker and text, the expected spans in the dev-set format, and two voice ids.

- It calls `SynthesizeSpeech` per turn with `Engine: standard`, `OutputFormat: pcm` and `SampleRate: 16000`
  (signed 16-bit mono little-endian). Only the standard engine has voices in us-east-2, the account's one Region.
- It joins the turns with 400 ms of silence and writes one WAV with the `wave` module. This is our upload format,
  so a sample goes through exactly the pipeline a recording does.
- Turn timestamps come from sample counts, so each clip has an exact ground-truth transcript with `start_ms` and
  `end_ms`.
- Four clips of 30–60 s, each covering several labels: a firm promise with a date, a hedge, a conditional, a
  request, and a refusal or a reported promise.
- Standard voices cost $4 per million characters, so four clips of about 900 characters cost under $0.02. The
  script runs once, with the new account's profile. The WAVs are committed under
  `frontend/public/samples/` for playback and deployed to `samples/` in the bucket.

The dialogues are new text, not the dev-set utterances, so they don't tune the prompt on its own data. They can
seed Part 3's audio evaluation items.

## Backend changes

- **Turn timestamps.** `Turn.start_ms` and `Turn.end_ms` are optional non-negative ints, and `end_ms ≥ start_ms`
  when both are set. `API_VERSION` becomes `0.2.0` and `openapi.json` is regenerated in the same commit. Text mode
  is unaffected.
- **`transcription/`**:
  - `Transcriber` protocol: `start(audio: AudioRef, job_id) -> None` and
    `result(job_id) -> list[TimedTurn]`.
  - `turns.py`: a pure function from Transcribe's output JSON to turns. It groups consecutive items by speaker
    label, attaches punctuation, and takes the first and last item times. It maps `spk_0` and `spk_1` to the
    visitor's names in order of first speech, defaulting to `Speaker 1` and `Speaker 2`.
  - `aws.py`: `AwsBatchTranscriber` on boto3.
  - `FakeTranscriber`.

  The diarization pages didn't load during research, so `turns.py` is tested against a real output captured in the
  measurement step (with the transcript text replaced).
- **`jobs/`**:
  - `JobStore` protocol, with memory and DynamoDB implementations.
  - `service.py`, which creates jobs, computes the dedup key and checks the duration.
  - `worker.py`, with the Transcribe event handler and the text-job handler.
  - `audio.py`, which validates the WAV header.
  - `samples.py`, the sample manifest.
- **API routes:**
  - `POST /uploads`
  - `POST /jobs` (sources: `upload_id`, `sample_id`, `transcript`)
  - `GET /jobs/{id}`
  - `POST /feedback`
  - `GET /samples`, which lists the sample clips
- **Error codes**, in the existing error body:
  - `audio_too_long` and `audio_invalid` (422)
  - `upload_not_found` and `job_not_found` (404)
  - `rate_limited` (429, with `Retry-After`)
  - `daily_budget_exhausted` (503, with `Retry-After` set to UTC midnight)
  - `transcription_failed`, as a job status
- **Rate limiting**, ported from FlakeHunter: fixed windows keyed by source IP, counted in DynamoDB.
  - `POST /uploads` and `POST /jobs`: 20 an hour
  - `POST /analyze`: 30 an hour
  - `POST /feedback`: 120 an hour
  - `GET /jobs/{id}`: 120 a minute

  The HTTP API stage throttle (10 rps, burst 20) caps the total.
- **Daily spend cap.** A `spend#YYYY-MM-DD` item in the guardrails table is incremented atomically:
  - by the estimated Transcribe cost when a job starts
  - by `metadata.cost_usd` after each model call, which Part 1 already computes

  `POST /jobs` and `POST /analyze` refuse new work once the day's total reaches `DAILY_BUDGET_USD` ($5, set at
  deploy with `-c dailyBudgetUsd=…`). An audio job costs about $0.025, almost all of it Transcribe, and a text job
  about $0.001 on Haiku, so $5 allows about 200 full-length audio jobs a day.

  The cap has to live in the app: AWS Budgets refreshes up to three times a day, 8–12 hours apart, and never sees
  Anthropic charges. The $30 monthly AWS budget kill switch (`-c monthlyBudgetUsd=…`) stays as a backstop, and
  `docs/deploying.md` asks you to set a spend limit in the Anthropic console.

  At this cap the monthly budget is the tighter of the two limits. About six days of maximum use reach $30, and
  the kill switch then stops the functions until you lift it.
- **Feedback.** `{job_id, span_index, vote, consent}`. The server copies the label from the job record; the client
  never supplies it. Every vote is stored as a vote item (`job_id`, `span_index`, `label`, `vote`) with no TTL,
  holding no text and no IP. With consent, the server also writes a content item, linked by the feedback id,
  holding the transcript and the spans copied from the job record, so it can't be used to store arbitrary text.
  The content item expires after 90 days by TTL. The tickbox states that: "Keep this transcript for up to 90 days
  to improve the labels."
- **Layering** (`tests/test_layout.py`):
  - `transcription` imports neither `extractor`, `jobs`, `api` nor `evaluation`.
  - `jobs` imports neither `api` nor `evaluation`.
  - `evaluation` gains `jobs` as a forbidden import.
  - `schemas` stays a leaf.
- **New dependencies:** `boto3` and `mangum` (approved in the brief), and the dev-only
  `types-boto3[s3,dynamodb,transcribe,ssm,lambda]` for mypy strict. The stubs are not in the Lambda bundle.

## Frontend (frontend/)

- **Next.js 16, App Router, strict TypeScript, `output: 'export'`.** Amplify's SSR compute documents Next.js 12–15,
  and the site needs no server code (no secrets, no request-time rendering), so a static export removes that
  constraint. Static export leaves out cookies, rewrites, Server Actions and request-dependent route handlers; the
  demo uses none of them.
- **Typed client.**
  - openapi-typescript generates `src/api/schema.d.ts` from `../openapi.json`, and openapi-fetch calls the API.
  - `NEXT_PUBLIC_API_BASE_URL` is set at build time from the stack output.
  - `bun run gen:api` regenerates the client, and CI fails if the result differs from what is committed.
- **Bun** for installs and scripts, and **Biome** for linting, formatting and import order, as in FlakeHunter and the
  cc-practices TypeScript rules. One `biome.json` at the repo root covers `frontend/` and `infra/`.
- **Components:**
  - `Recorder`: consent notice before `getUserMedia`, a 60 s countdown that stops itself, WAV encoding
  - `SamplePicker`, with playback
  - `TextInput`, with prompt chips
  - `CallDetails`: call date and two speaker names
  - `JobStatus`: uploading, transcribing, analyzing, done
  - `Transcript`: spans highlighted per label, and turn timestamps in audio mode
  - `LedgerCard`
  - `NearMisses`
  - `Feedback`, with a consent tickbox
- **Accessibility.**
  - Every label has a text badge and a pattern as well as a colour.
  - All controls are reachable and operable by keyboard, with visible focus.
  - The status line is an `aria-live` region.
  - The layout is single-column below 640 px.
- **Tests.** Vitest and Testing Library for the components: the countdown stopping at 60 s with fake timers, WAV
  encoding of a known buffer, and rendering of each label, HEDGED as soft and the CONDITIONAL condition. One
  Playwright test runs text mode against the built site, with the API mocked by `page.route`.

## CI and tooling

`.github/workflows/ci.yml` runs on every push and pull request. Actions are pinned to commit SHAs with the tag in a
comment, and the workflow has `permissions: contents: read`. There are three jobs:

- **backend**: `uv sync --locked`, pytest (including the `openapi.json` freshness test), Ruff check and format,
  mypy.
- **frontend**: `bun install --frozen-lockfile`, `biome ci .`, `tsc --noEmit`, Vitest, regenerating the client and
  checking `git diff --exit-code`, `next build`, and Playwright on Chromium.
- **infra**: `bun install --frozen-lockfile`, `bun test`, and `cdk synth` with no credentials. Synth uses a context
  flag that pins the account to a placeholder.

Tests make no calls to AWS or Anthropic. Installing packages and Playwright's browser is the only network use.
`.claude/cc-practices.json` gains `typescript`, with format, lint, typecheck and test commands for `frontend/`
and `infra/`.

## Measuring latency

`scripts/measure_latency.py` runs against the deployed API. It submits 20 jobs from one sample clip, each with a
different call date so none is deduplicated, polls each to completion, and prints p50 and p95 for every stage and
the total. The README records the result against the 10 s target. A second script, `scripts/check_audio_gone.py`,
uploads a clip, waits for its job, and asserts that the object, the transcript output and the Transcribe job are
gone. That is the "audio is gone" proof the brief asks for, run after the deploy. The worker's unit tests prove the
same thing with fakes.

**Latency test before the backend work.** Once the new account and its profile exist, a throwaway script (in the
session scratchpad, not committed) does the following:

1. Generates one 60 s two-voice clip with Polly and uploads it to a temporary bucket.
2. Runs 10 batch jobs with speaker labels, timing each from `StartTranscriptionJob` to `COMPLETED`.
3. Saves one output JSON.
4. Deletes the objects, the bucket and the jobs.

Budget about $0.30: up to $0.24 for Transcribe at the highest plausible rate, plus Polly. If batch transcription
takes 40 s or more, the transcription decision is reopened before any code depends on it. The saved output, with
its text replaced by our own script's text, becomes the fixture for the `turns.py` tests.

## File tree (new and changed)

```text
.github/workflows/ci.yml
.claude/cc-practices.json                      typescript added
biome.json                                     shared by frontend/ and infra/
package.json, bun.lock                         root dev dependency on @biomejs/biome
docs/plans/part-2-audio-and-deploy.md          this document
docs/decisions/0002-batch-transcription.md     one ADR per accepted decision
docs/decisions/0003-job-resource.md
docs/decisions/0004-mangum-and-zip.md
docs/decisions/0005-cdk-typescript.md
docs/decisions/0006-polly-sample-clips.md
docs/decisions/0007-separate-aws-account.md
docs/deploying.md                              account setup, SCP, DNS delegation, deploy, kill-switch reset
backend/pyproject.toml                         boto3, mangum, types-boto3 (dev); scikit-learn → eval group
backend/samples/dialogues.jsonl                scripted dialogues + expected spans
backend/scripts/make_samples.py                Polly → WAV (run once, by you)
backend/scripts/measure_latency.py
backend/scripts/check_audio_gone.py
backend/src/commitment_tracker/
  schemas.py                                   Turn.start_ms / end_ms; job and feedback models
  settings.py                                  bucket, tables, limits, daily budget
  transcription/{__init__,protocol,turns,aws,fake}.py
  jobs/{__init__,store,dynamo_store,service,worker,audio,samples}.py
  guardrails/{__init__,ratelimit,spend}.py
  api/app.py                                   new routes, CORS for local dev
  lambda_handlers.py                           Mangum API handler, worker handler, SSM settings
backend/tests/                                 one test module per new module; fixtures/transcribe-output.json
frontend/                                      Next.js app (package.json, next.config.ts, src/, tests/, e2e/)
frontend/public/samples/*.wav
infra/bin/commitment-tracker.ts
infra/lib/{api-stack,web-stack}.ts
infra/lambda/budget-stop/index.mjs
infra/scp/commitment-tracker-guardrails.json   adapted from FlakeHunter; attached by you
infra/scripts/bundle-api.ts
infra/test/{stacks,iam,budgetStop,bundle}.test.ts, synth-worker.ts
README.md                                      demo, architecture, deploy, costs, screenshot, measured latency
```

## Commit sequence

Each commit is small, test-first where practical, and Conventional. `feat:` is used only where the API or the demo
changes visibly.

1. `docs: add the Part 2 design` (this document)
2. `docs: add ADRs 0002–0007` (after approval)
- *You:* create the account, then attach the SCP (I draft it first, in `infra/scp/`), set up the profile and
  bootstrap CDK. *Me:* run the latency test with that profile and report back before step 3.
3. `build: move scikit-learn to an eval group; add boto3, mangum and types-boto3`
4. `feat(api): add optional turn timestamps` (API_VERSION 0.2.0, openapi.json)
5. `feat: map Transcribe output to timed turns` (protocol, `turns.py`, fake)
6. `feat: add the AWS batch transcriber` (stubbed boto3 client)
7. `feat: add the job store` (memory and DynamoDB, stubbed)
8. `feat(api): add presigned uploads and WAV validation`
9. `feat(api): add the job resource` (`POST /jobs`, `GET /jobs/{id}`, dedup, duration cap, samples)
10. `feat: add the job worker` (Transcribe event and text jobs, deletion, stage latency)
11. `feat(api): add per-client rate limiting`
12. `feat(api): add the daily spend cap`
13. `feat(api): add span feedback`
14. `feat: add Lambda handlers and SSM settings`
15. `chore: add the Polly sample script and dialogues` (you run it; the WAVs follow in their own commit)
16. `build(infra): scaffold the CDK app and the Lambda bundle`
17. `feat(infra): add the API stack` (bucket, tables, functions, EventBridge rule, IAM tests)
18. `feat(infra): add the budget kill switch and alarms`
19. `feat(infra): add the Amplify web stack`
20. `feat(web): scaffold the Next.js app and the typed client`
21. `feat(web): add text mode and the results view`
22. `feat(web): add recording and upload`
23. `feat(web): add sample clips`
24. `feat(web): add span feedback`
25. `feat(web): add prompt chips and the Playwright test`
26. `ci: add backend, frontend and infra checks`
27. `chore: add TypeScript checks to cc-practices`
28. `docs: add the deploy guide`
29. After your deploy: `docs: record measured latency and add the README demo section`

## Risks

- **Latency.** Batch transcription probably misses the 10 s target, and nothing in this design brings it under
  10 s. The fix is live streaming during recording (section 1), which is out of scope here.
- **Diarization on two similar voices.** Polly voices are distinct, but a visitor recording alone, or two people on
  one laptop microphone, may get one speaker or swapped labels. The UI lets the visitor swap the two names after
  the results arrive, a client-side relabel with no new job.
- **Safari.** MediaRecorder in Safari produces MP4/AAC. `decodeAudioData` handles it, but the Recorder needs a
  manual check in Safari on iOS, which Playwright on Chromium doesn't cover.
- **Amplify and Next.js 16.** A static export is just files, but Amplify detects Next.js apps and may pick its SSR
  platform. The web stack sets the platform to `WEB` and the artifacts to `out/`, and the first deploy confirms it.
- **Cost of abuse.** The rate limits, the stage throttle and the daily cap together bound a day's worst case at
  `DAILY_BUDGET_USD`, plus requests refused before any model or Transcribe call. A sustained flood reaches the
  $30 monthly budget in about six days and stops the demo until you reset the kill switch.

## Decisions (2026-10-21)

Settled one by one before acceptance:

1. **AWS account:** a new member account for this project, with its own SCP, budget and delegated hosted zone
   (ADR 0007).
2. **Demo model:** `claude-haiku-5-5` on the deployed stack until Part 3 compares models; the settings default stays
   `claude-opus-5-5`.
3. **Text mode:** the frontend sends text through `POST /jobs`; `POST /analyze` is unchanged for API clients.
4. **TypeScript lint and format:** Biome, one root `biome.json`, as in FlakeHunter and the cc-practices rules.
5. **boto3 types:** `types-boto3[s3,dynamodb,transcribe,ssm,lambda]`, dev only.
6. **Latency test first:** about $0.30 in the new account before the backend work, with one output captured as the
   `turns.py` fixture.
7. **Feedback retention:** votes kept with no text and no TTL; consented transcripts in a separate item deleted
   after 90 days.
8. **Spending limits:** a $5 daily cap enforced by the API and a $30 monthly AWS budget kill switch, both set at
   deploy time.

## Sources

| Claim | Page and section |
| --- | --- |
| Streaming formats are PCM (not WAV), FLAC and Ogg Opus; 50–200 ms chunks; stream "as close to real-time as possible" | [Transcribing streaming audio](https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html) |
| Batch formats include WAV, FLAC, MP3, MP4, Ogg and WebM; streaming formats; sample rates | [Data input and output](https://docs.aws.amazon.com/transcribe/latest/dg/how-input.html) |
| Streaming speaker partitioning (`ShowSpeakerLabel`), en-US | [Identifying speakers in real-time streams](https://docs.aws.amazon.com/transcribe/latest/dg/diarization-streaming.html) (from search; the page body didn't load) |
| Batch speaker labels | [Identifying speakers in audio files](https://docs.aws.amazon.com/transcribe/latest/dg/diarization-batch.html) (page body didn't load; confirmed in the spike) |
| The Python streaming SDK is experimental, uses awscrt, and paces a file in real time with 100 ms chunks | [AWS SDK for Python: stream audio with Amazon Transcribe](https://docs.aws.amazon.com/sdk-for-python/v1/guide/getting-started-transcribe-streaming.html) |
| `amazon-transcribe` is described as early alpha | [PyPI: amazon-transcribe 0.6.1](https://pypi.org/project/amazon-transcribe/0.6.1/) |
| Billed per second with no minimum; example prices $0.006/min batch, $0.01/min streaming (us-east-1); free tier 60 min/month for 12 months | [Amazon Transcribe pricing](https://aws.amazon.com/transcribe/pricing/) (the tier table didn't render; the us-east-2 rate is confirmed at deploy) |
| A 1-minute file took 20–25 s in batch (anecdotal) | [re:Post: Latency while using AWS Transcribe batch](https://repost.aws/questions/QU71NgjzoMRXmQLIFJyfUWkQ/latency-while-using-aws-transcribe-batch-process) |
| `Transcribe Job State Change` event, `TranscriptionJobName`, `TranscriptionJobStatus` | [Using Amazon EventBridge with Amazon Transcribe](https://docs.aws.amazon.com/transcribe/latest/dg/monitoring-events.html) |
| HTTP API maximum integration timeout 30 s, not adjustable | [HTTP API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html) |
| Presigned POST `content-length-range` condition | [boto3 `generate_presigned_post`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/generate_presigned_post.html); [POST policy](https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-HTTPPOSTConstructPolicy.html) |
| uv zip recipe for Lambda; 250 MB zip limit | [Using uv with AWS Lambda](https://docs.astral.sh/uv/guides/integration/aws-lambda/) |
| arm64 wheels with `manylinux2014_aarch64` | [Working with .zip archives for Python Lambda functions](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html) |
| Mangum 0.20.0 (Dec 2025) and 0.21.0 (Feb 2026), Python 3.9–3.14 | [PyPI mirror: mangum](https://simple-repository.app.cern.ch/project/mangum) (to confirm on pypi.org when adding it) |
| Lambda Web Adapter zip setup; non-HTTP events go to `/events` | [aws-lambda-web-adapter fastapi-zip example](https://github.com/awslabs/aws-lambda-web-adapter/blob/main/examples/fastapi-zip) |
| Budgets refresh up to three times a day, 8–12 hours apart | [Managing your costs with AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html) |
| Static export: `output: 'export'` and unsupported features | [Next.js static exports](https://nextjs.org/docs/app/guides/static-exports) |
| Amplify SSR compute supports Next.js 12–15; platform values `WEB` and `WEB_COMPUTE` | [Amplify support for Next.js](https://docs.aws.amazon.com/amplify/latest/userguide/ssr-amplify-support.html) |
| Next.js 16.4.0 released 7 October 2026 | [Wikipedia: Next.js](https://en.wikipedia.org/wiki/Next.js) (secondary; confirmed against npm when scaffolding) |
| Polly PCM at 8000 or 16000 Hz, signed 16-bit mono little-endian | [AWS CLI `polly synthesize-speech`](https://docs.aws.amazon.com/cli/latest/reference/polly/synthesize-speech.html) |
| Polly prices: standard $4, neural $16, generative $30 per million characters | [Amazon Polly pricing](https://aws.amazon.com/polly/pricing/) |
