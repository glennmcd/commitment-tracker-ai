# 0006. Sample clips generated with Amazon Polly

Date: 2026-10-21 · Status: Accepted

## Context

The demo offers canned two-person clips for visitors who don't want to record. Each clip should have a known
transcript and known labels, so a wrong result is visibly wrong and the clips can later seed audio evaluation
items. Recording real people would need their consent, and would give no exact timestamps.

## Decision

- **Generation.** `backend/scripts/make_samples.py` reads scripted dialogues from `backend/samples/dialogues.jsonl`.
  Each dialogue has two Polly voices and its expected spans.
- **Synthesis.** Polly synthesizes each turn as 16 kHz mono PCM. The script joins the turns with 400 ms of silence
  and writes one WAV per dialogue with the standard library's `wave` module.
- **Clips.** Four clips of 30–60 s, written as new text rather than taken from the dev set. Each covers several
  labels.
- **Running it.** The owner runs the script once, with the project account's profile.
- **Storage.** The WAVs are committed under `frontend/public/samples/` for playback, and CDK deploys them to
  `samples/` in the audio bucket.

## Consequences

- **Same pipeline.** Sample clips use the upload format, so they go through the pipeline a recording does,
  transcription included.
- **Ground truth.** Turn start and end times come from sample counts, so each clip has exact ground-truth
  timestamps.
- **Realism.** Synthetic voices are cleaner and more distinct than a real call. Diarization on samples will look
  better than on recordings.
- **Cost.** Under $0.15 once. `polly:*` can come off the account's SCP allow-list afterwards.

## Alternatives considered

- **Recorded volunteers.** Needs consent and storage terms, and gives no exact timestamps.
- **Public-domain call recordings.** Hard to find with commitments in them, and with no labels.
