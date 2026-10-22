# 0002. Batch transcription with Amazon Transcribe

Date: 2026-10-21 · Status: Accepted

## Context

Part 2 turns recordings and sample clips of up to 60 seconds into turns, each with a speaker, the text and its
start and end times, for the Part 1 extractor. Amazon Transcribe offers batch jobs and streaming sessions, and both
can label two speakers. The server always holds a finished file: either an upload or a sample clip. AWS asks for
streamed audio to arrive "as close to real-time as possible", so streaming a finished 60-second file takes about 60
seconds. boto3, the GA Python SDK, has no streaming support. The two Python streaming clients are marked
experimental and early alpha.

## Decision

Use batch jobs (`StartTranscriptionJob`):

- **Input:** a 16 kHz mono PCM WAV from our bucket.
- **Speakers:** `ShowSpeakerLabels` with `MaxSpeakerLabels: 2`.
- **Output:** written to our bucket under `transcripts/`.
- **Completion:** a `Transcribe Job State Change` event in EventBridge starts the next stage, so no Lambda waits on
  the job.
- **Adapter:** the `Transcriber` protocol hides the mode from the rest of the backend, as the model adapter does
  for the model.

## Consequences

- **Latency.** The latency test on 2026-10-21 measured transcription of a 59 s clip at 15.4 s p50 and 15.8 s p95,
  over 10 jobs with no queueing. That is well under the 40 s that would have reopened this decision. The whole job
  should take about 17–19 s with Haiku 5.5, which misses the brief's 10 s target. The README reports the deployed
  p50 and p95.
- **Cleanup.** After reading the output, the worker deletes the audio, the output object and the Transcribe job.
  Nothing persists in the service-managed location, which keeps results for 90 days.
- **Format.** Every upload is WAV, so the browser converts recordings before uploading (ADR 0003).

## Alternatives considered

- **Server-side streaming.** Slower than batch for a finished file when paced in real time. Sending faster than
  real time is undocumented, and the only Python clients are pre-GA.
- **Live streaming from the browser while the visitor speaks.** The only way under 10 s. It needs a server-controlled
  relay, because a presigned Transcribe URL can't enforce the 60 s cap, and sample clips would also have to stream
  as they play. Deferred until the measured latency shows whether it's needed.
