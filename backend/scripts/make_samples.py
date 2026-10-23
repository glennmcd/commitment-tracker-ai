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
import io
import json
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.jobs.audio import MAX_AUDIO_SECONDS, SAMPLE_RATE_HZ
from commitment_tracker.jobs.samples import SampleClip
from commitment_tracker.schemas import Turn

if TYPE_CHECKING:
    from types_boto3_polly import PollyClient

BACKEND = Path(__file__).resolve().parents[1]
GAP_MS = 400
USD_PER_MILLION_CHARS = 4.0
CHARS_PER_SECOND = 14  # a rough rate for Polly's standard voices, for the dry-run estimate

Synthesizer = Callable[[str, str], bytes]  # (text, voice id) -> 16 kHz mono 16-bit PCM


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
    order = list(dict.fromkeys(turn.speaker for turn in dialogue.turns))
    return dict(zip(order, dialogue.voices, strict=True))


@dataclass(frozen=True)
class Clip:
    id: str
    pcm: bytes
    turns: list[Turn]  # with start_ms and end_ms

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) // 2 * 1000 // SAMPLE_RATE_HZ


def build_clip(dialogue: Dialogue, synthesize: Synthesizer) -> Clip:
    voices = speaker_voices(dialogue)
    silence = b"\x00\x00" * (SAMPLE_RATE_HZ * GAP_MS // 1000)
    parts: list[bytes] = []
    timed: list[Turn] = []
    samples = 0
    for index, turn in enumerate(dialogue.turns):
        if index:
            parts.append(silence)
            samples += len(silence) // 2
        pcm = synthesize(turn.text, voices[turn.speaker])
        start = samples * 1000 // SAMPLE_RATE_HZ
        samples += len(pcm) // 2
        parts.append(pcm)
        timed.append(
            Turn(
                speaker=turn.speaker,
                text=turn.text,
                start_ms=start,
                end_ms=samples * 1000 // SAMPLE_RATE_HZ,
            )
        )
    clip = Clip(id=dialogue.id, pcm=b"".join(parts), turns=timed)
    if clip.duration_ms > MAX_AUDIO_SECONDS * 1000:
        raise ValueError(f"{dialogue.id}: {clip.duration_ms} ms is over {MAX_AUDIO_SECONDS} s")
    return clip


def wav_bytes(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE_HZ)
        out.writeframes(pcm)
    return buffer.getvalue()


def polly_synthesizer(client: "PollyClient | Any") -> Synthesizer:
    def synthesize(text: str, voice: str) -> bytes:
        response = client.synthesize_speech(
            Engine="standard",
            OutputFormat="pcm",
            SampleRate=str(SAMPLE_RATE_HZ),
            TextType="text",
            VoiceId=voice,
            Text=text,
        )
        pcm: bytes = response["AudioStream"].read()
        if len(pcm) % 2:
            raise ValueError("Polly returned a stream that is not whole 16-bit samples")
        return pcm

    return synthesize


def _truth(dialogue: Dialogue, clip: Clip) -> dict[str, Any]:
    item = EvalItem(
        id=dialogue.id,
        call_date=dialogue.call_date,
        turns=clip.turns,
        tags=dialogue.tags,
        expected=dialogue.expected,
        note=dialogue.note,
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
