"""Amazon Transcribe batch output to timed turns, and timed turns to request `Turn`s.

A turn is a run of consecutive words with the same speaker label; Transcribe's own `audio_segments`
can split one speaker's run in two, so they are not used. Punctuation items carry no times and
attach to the previous word with no space. Validation errors never include the transcript text.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.protocol import TimedTurn


class TranscriptFormatError(ValueError):
    """The job output does not have the shape Transcribe documents."""


class _Output(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Alternative(_Output):
    content: str


class _Item(_Output):
    type: Literal["pronunciation", "punctuation"]
    alternatives: list[_Alternative] = Field(min_length=1)
    start_time: Decimal | None = Field(default=None, ge=0)
    end_time: Decimal | None = Field(default=None, ge=0)
    speaker_label: str | None = None

    @model_validator(mode="after")
    def _timed_words(self) -> Self:
        if self.type == "pronunciation":
            if self.start_time is None or self.end_time is None:
                raise ValueError("a word needs a start and an end time")
            if self.end_time < self.start_time:
                raise ValueError("a word must not end before it starts")
        return self


class _Results(_Output):
    items: list[_Item]


class _JobOutput(_Output):
    results: _Results


def _ms(seconds: Decimal | None) -> int:
    assert seconds is not None  # checked by _Item for words
    return int((seconds * 1000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def to_timed_turns(output: object) -> list[TimedTurn]:
    """Turns from a parsed batch job output JSON, speakers numbered in order of first speech."""
    try:
        items = _JobOutput.model_validate(output).results.items
    except ValidationError as error:
        raise TranscriptFormatError(f"unexpected Transcribe output: {error}") from None

    speakers: dict[str | None, int] = {}
    turns: list[TimedTurn] = []
    words: list[str] = []
    speaker = start_ms = end_ms = 0

    def flush() -> None:
        if words:
            turns.append(TimedTurn(speaker, " ".join(words), start_ms, end_ms))

    for item in items:
        content = item.alternatives[0].content
        if item.type == "punctuation":
            if words:
                words[-1] += content
            continue
        label = speakers.setdefault(item.speaker_label, len(speakers))
        if not words or label != speaker:
            flush()
            words, speaker, start_ms = [], label, _ms(item.start_time)
        words.append(content)
        end_ms = _ms(item.end_time)
    flush()
    return turns


def name_turns(turns: Sequence[TimedTurn], names: Sequence[str] = ()) -> list[Turn]:
    """Request turns with the visitor's names; speakers without one become `Speaker N`."""
    return [
        Turn(
            speaker=names[turn.speaker]
            if turn.speaker < len(names)
            else f"Speaker {turn.speaker + 1}",
            text=turn.text,
            start_ms=turn.start_ms,
            end_ms=turn.end_ms,
        )
        for turn in turns
    ]
