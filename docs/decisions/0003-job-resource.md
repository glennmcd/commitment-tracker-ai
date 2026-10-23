# 0003. A job resource for audio and the demo's text mode

Date: 2026-10-21 · Status: Accepted

## Context

Transcription and extraction together take longer than API Gateway holds a request open: an HTTP API has a hard
30-second integration timeout. Audio must not pass through API Gateway, and it must be gone from S3 once
transcribed. Clips are capped at 60 seconds, and the server must enforce that as well as the browser.

## Decision

- **Upload.** `POST /uploads` returns a presigned S3 POST for `uploads/<uuid>.wav`, with a `content-length-range`
  of at most 1,920,044 bytes. That is 60 s of 16 kHz mono 16-bit PCM plus a 44-byte header.
- **Recording format.** The browser converts the recording to that format with the Web Audio API, so the size cap
  also caps the duration.
- **Starting a job.** `POST /jobs` takes an `upload_id`, a `sample_id` or a `transcript`, plus the call date and
  speaker names. The API reads the WAV header, rejects a longer or malformed clip (`audio_too_long`,
  `audio_invalid`), and stores the job in DynamoDB with a one-hour TTL.
- **Deduplication.** The job id is a hash of the audio, the call date and the speaker names, so a retried upload
  returns the existing job.
- **Running the job.** Transcribe's completion event (ADR 0002) or, for text, a direct async invoke runs a worker
  Lambda. The worker analyzes the turns, deletes the audio and records per-stage latency.
- **Polling.** The browser polls `GET /jobs/{id}` until the status is `done` or `failed`.
- **Text mode.** The frontend sends text through `POST /jobs` as well. `POST /analyze` stays unchanged for API
  clients.

## Consequences

- **One flow.** All three input modes share one status line, one results view and one feedback path. Feedback
  copies the transcript and labels from the job record, never from the client.
- **Overhead.** Text results pay about 0.5–1 s for the invocation and the polling.
- **Retention.** A transcript lives only in its job record until the TTL removes it. A one-day lifecycle rule on
  `uploads/` and `transcripts/` backs up the worker's deletes.
- **Who can read a job.** Anyone holding the same audio who guesses the call date and the names could read a job,
  which only reveals a transcript of audio they already have.

## Alternatives considered

- **A synchronous request.** Exceeds the gateway timeout for audio.
- **Step Functions.** A state machine for two stages adds a service, IAM and tests for little gain over one event
  rule and one worker.
- **Frontend text mode on `/analyze`.** A second flow in the frontend, and consented feedback would have to accept
  the transcript from the client.
