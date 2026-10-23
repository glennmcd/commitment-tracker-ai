# 0006. Sample clips generated with Amazon Polly

Date: 2026-10-21 · Status: Accepted

## Context

The demo offers canned two-person clips for visitors who don't want to record. Each clip should have a known
transcript and known labels, so a wrong result is visibly wrong and the clips can later seed audio evaluation
items. Recording real people would need their consent, and would give no exact timestamps.

## Decision

- **Generation.** `backend/scripts/make_samples.py` reads scripted dialogues from `backend/samples/dialogues.jsonl`.
  Each dialogue has two Polly voices and its expected spans.
- **Voices.** Polly's standard engine in us-east-2, the account's only Region. The neural, generative and long-form
  engines list no voices there (checked with `describe-voices` on 2026-10-21). Two contrasting US English voices,
  such as Matthew and Joanna.
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
- **Realism.** Standard voices sound noticeably synthetic, and cleaner and more distinct than a real call.
  Diarization on samples will look better than on recordings. In the latency test, a 59 s clip with Matthew and
  Joanna came back with every turn assigned to the right speaker.
- **Cost.** Standard voices cost $4 per million characters, so four clips of about 900 characters cost under $0.02
  once. `polly:*` can come off the account's SCP allow-list afterwards.

## Alternatives considered

- **Neural or generative voices from us-east-1.** More natural speech, but it needs a temporary Region exemption in
  the account's SCP for a one-off script. The clips exist to exercise the pipeline, not to sound human.

- **Recorded volunteers.** Needs consent and storage terms, and gives no exact timestamps.
- **Public-domain call recordings.** Hard to find with commitments in them, and with no labels.
