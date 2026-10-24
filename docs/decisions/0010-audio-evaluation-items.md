# 0010. Audio evaluation items: Polly and human recordings

Date: 2026-10-23 · Status: Accepted

## Context

The demo transcribes audio before extraction, and transcription errors and speaker mix-ups cost accuracy. Measuring
that cost needs audio for items whose text labels are known. Polly gives clean audio with an exact transcript, but
its distinct synthetic voices understate the penalty a real call pays. Audio files don't belong in git.

## Decision

- **Mix.** 30 `test` items get audio: 20 synthesised with Polly (two standard voices, as in ADR 0006) and 10
  recorded by two different people per clip, read from the script with natural delivery through the demo's
  Recorder (16 kHz mono WAV). At least 20 of the 30 are multi-turn, and every label is represented.
- **Manifest.** `eval/sets/audio/clips.jsonl` maps each clip to its `test` item id and records its source
  (`polly` or `human`), voices or role assignment, duration and SHA-256. Speakers are recorded by role id, never by
  name.
- **Storage.** A private, versioned S3 bucket in the project account, added to the API stack and deployed by the
  owner. `uv run eval-audio make` regenerates the Polly clips, `eval-audio upload` stores new clips, and
  `eval-audio fetch` downloads into the git-ignored `eval/.audio/` and checks hashes.
- **Scoring.** `uv run eval --set audio --transcribe` transcribes each clip with the existing batch transcriber
  and caches the turns by audio hash. Transcribed turns are aligned to the item's turns by word overlap
  (`difflib`), then matched with the existing span rules. Turn-count mismatches and speaker swaps are counted.
- **Penalty.** Ledger F1 on the transcribed clips minus ledger F1 on the same items as text, per configuration and
  separately for the Polly and human slices. It is a manual, local run.

## Consequences

- **An honest penalty.** The human slice shows what a real recording costs; the Polly slice isolates transcription
  on clean audio, and the gap between them shows how much Polly understates it.
- **Human clips can't be regenerated.** They are fetched by hash, so losing the bucket loses them; versioning
  protects against accidental overwrites.
- **Cost.** Polly is under $0.03 once; Transcribe about $0.25 for one pass over 30 clips, shared by every
  configuration through the transcript cache.
- **Privacy.** Two people's voices stay in a private bucket, not on the public site or in a release.

## Alternatives considered

- **Polly only.** No recording effort, but it understates the penalty the README reports.
- **Human recordings only.** Most realistic, but 30 two-person recordings is a lot of effort for this project.
- **GitHub release assets or Git LFS.** Easy to fetch, but public, and LFS adds quota and tooling.
