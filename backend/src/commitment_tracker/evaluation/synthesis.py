"""Two-voice speech for scripted transcripts, as used by the demo's sample clips (ADR 0006) and the
Polly evaluation clips (docs/plans/part-3-evaluation.md, section 3).

Each turn is spoken in its speaker's voice and turns are joined by 400 ms of silence into one
16 kHz mono 16-bit WAV, the upload format, so a clip goes through the pipeline a recording does.
Turn times come from sample counts, which gives each clip an exact ground-truth transcript.
"""

import io
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from commitment_tracker.jobs.audio import MAX_AUDIO_SECONDS, SAMPLE_RATE_HZ
from commitment_tracker.schemas import Turn

GAP_MS = 400

Synthesizer = Callable[[str, str], bytes]  # (text, voice id) -> 16 kHz mono 16-bit PCM


@dataclass(frozen=True)
class Clip:
    id: str
    pcm: bytes
    turns: list[Turn]  # with start_ms and end_ms

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) // 2 * 1000 // SAMPLE_RATE_HZ


def assign_voices(turns: Sequence[Turn], voices: Sequence[str]) -> dict[str, str]:
    """The first speaker to talk gets the first voice, the next speaker the second."""
    order = list(dict.fromkeys(turn.speaker for turn in turns))
    if len(order) != len(voices):
        raise ValueError(f"{len(order)} speakers but {len(voices)} voices")
    return dict(zip(order, voices, strict=True))


def build_clip(
    clip_id: str, turns: Sequence[Turn], voices: dict[str, str], synthesize: Synthesizer
) -> Clip:
    silence = b"\x00\x00" * (SAMPLE_RATE_HZ * GAP_MS // 1000)
    parts: list[bytes] = []
    timed: list[Turn] = []
    samples = 0
    for index, turn in enumerate(turns):
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
    clip = Clip(id=clip_id, pcm=b"".join(parts), turns=timed)
    if clip.duration_ms > MAX_AUDIO_SECONDS * 1000:
        raise ValueError(f"{clip_id}: {clip.duration_ms} ms is over {MAX_AUDIO_SECONDS} s")
    return clip


def wav_bytes(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE_HZ)
        out.writeframes(pcm)
    return buffer.getvalue()


def polly_synthesizer(client: Any) -> Synthesizer:
    """`client` is a boto3 Polly client (its type stubs are not installed)."""

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
