"""Make the demo's sample clips with Amazon Polly (ADR 0006). The owner runs this once.

    uv run python scripts/make_samples.py --profile <aws profile> [--dry-run]

Reads scripted two-person dialogues from samples/dialogues.jsonl and speaks each turn with the
dialogue's two standard-engine voices (the only engine with voices in us-east-2), 16 kHz mono PCM.
Turns are joined by 400 ms of silence into one WAV per dialogue in the upload format, so a sample
goes through the pipeline a recording does. Turn times come from sample counts, which gives each
clip an exact ground-truth transcript. Writes:

- the WAVs, to frontend/public/samples/ (the demo plays them; CDK deploys them to the bucket)
- src/commitment_tracker/jobs/samples.json, the manifest the API bundles (id, title, duration,
  SHA-256)
- samples/ground-truth.jsonl, evaluation items with turn times, which can seed Part 3

`--dry-run` checks the dialogues and prints the character count and estimated cost without calling
AWS. Standard voices cost $4 per million characters.
"""

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from commitment_tracker.evaluation import synthesis
from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.synthesis import (
    Clip,
    Synthesizer,
    assign_voices,
    polly_synthesizer,
    wav_bytes,
)
from commitment_tracker.jobs.samples import SampleClip

BACKEND = Path(__file__).resolve().parents[1]
USD_PER_MILLION_CHARS = 4.0
CHARS_PER_SECOND = 14  # a rough rate for Polly's standard voices, for the dry-run estimate


class Dialogue(EvalItem):
    """An evaluation item plus what the script needs to speak it."""

    title: str = Field(min_length=1, max_length=100)
    voices: list[str] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _two_voices_two_speakers(self) -> "Dialogue":
        if len(set(self.voices)) != 2:
            raise ValueError("a dialogue needs two different voices")
        if len({turn.speaker for turn in self.turns}) != 2:
            raise ValueError("a dialogue needs exactly two speakers")
        return self


def load_dialogues(path: Path) -> list[Dialogue]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [Dialogue.model_validate_json(line) for line in lines]


def speaker_voices(dialogue: Dialogue) -> dict[str, str]:
    """The first speaker to talk gets the first voice, the other speaker the second."""
    return assign_voices(dialogue.turns, dialogue.voices)


def build_clip(dialogue: Dialogue, synthesize: Synthesizer) -> Clip:
    return synthesis.build_clip(dialogue.id, dialogue.turns, speaker_voices(dialogue), synthesize)


def _truth(dialogue: Dialogue, clip: Clip) -> dict[str, Any]:
    item = EvalItem(
        id=dialogue.id,
        call_date=dialogue.call_date,
        turns=clip.turns,
        tags=dialogue.tags,
        expected=dialogue.expected,
        note=dialogue.note,
        provenance=dialogue.provenance,
        review=dialogue.review,
    )
    dumped: dict[str, Any] = item.model_dump(mode="json")
    return dumped


def _dry_run(dialogues: Sequence[Dialogue]) -> None:
    total = 0
    for dialogue in dialogues:
        chars = sum(len(turn.text) for turn in dialogue.turns)
        total += chars
        print(
            f"{dialogue.id}: {len(dialogue.turns)} turns, {chars} characters, "
            f"about {chars // CHARS_PER_SECOND} s"
        )
    print(f"total {total} characters, about ${total * USD_PER_MILLION_CHARS / 1_000_000:.3f}")


def main(argv: Sequence[str] | None = None, *, polly: Any = None) -> int:
    parser = argparse.ArgumentParser(description="Make the demo's sample clips with Amazon Polly.")
    parser.add_argument("--profile", help="AWS profile of the project account")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--dry-run", action="store_true", help="check the dialogues, call nothing")
    parser.add_argument("--dialogues", type=Path, default=BACKEND / "samples" / "dialogues.jsonl")
    parser.add_argument(
        "--wav-dir", type=Path, default=BACKEND.parent / "frontend" / "public" / "samples"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=BACKEND / "src" / "commitment_tracker" / "jobs" / "samples.json",
    )
    parser.add_argument("--truth", type=Path, default=BACKEND / "samples" / "ground-truth.jsonl")
    args = parser.parse_args(argv)

    dialogues = load_dialogues(args.dialogues)
    if args.dry_run:
        _dry_run(dialogues)
        return 0

    if polly is None:
        import boto3

        polly = boto3.Session(profile_name=args.profile, region_name=args.region).client("polly")
    synthesize = polly_synthesizer(polly)

    wavs: dict[str, bytes] = {}
    manifest: list[dict[str, Any]] = []
    truth: list[str] = []
    for dialogue in dialogues:
        clip = build_clip(dialogue, synthesize)
        data = wav_bytes(clip.pcm)
        wavs[dialogue.id] = data
        entry = SampleClip(
            id=dialogue.id,
            title=dialogue.title,
            duration_ms=clip.duration_ms,
            sha256=hashlib.sha256(data).hexdigest(),
        )
        manifest.append(entry.model_dump())
        truth.append(json.dumps(_truth(dialogue, clip), ensure_ascii=False))
        print(f"{dialogue.id}: {clip.duration_ms / 1000:.1f} s, sha256 {entry.sha256[:12]}")

    # Write only once every clip has been made, so a failure leaves the previous files intact.
    args.wav_dir.mkdir(parents=True, exist_ok=True)
    for clip_id, data in wavs.items():
        (args.wav_dir / f"{clip_id}.wav").write_bytes(data)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    args.truth.write_text("\n".join(truth) + "\n", encoding="utf-8")
    print(f"wrote {len(wavs)} clips to {args.wav_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
