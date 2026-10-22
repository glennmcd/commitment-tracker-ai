"""Pydantic models shared by the API, the extractor and the evaluation.

These are the public contract: FastAPI builds the OpenAPI schema from them, and the extractor only
returns spans that pass `Span` validation. Every model hides input values in validation errors, so a
rejected transcript or quote never reaches a log line or error message.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

MAX_TURNS = 200
MAX_TRANSCRIPT_CHARS = 20_000


class Label(StrEnum):
    COMMITMENT = "COMMITMENT"
    HEDGED = "HEDGED"
    CONDITIONAL = "CONDITIONAL"
    SUGGESTION = "SUGGESTION"
    REQUEST = "REQUEST"
    REPORTED = "REPORTED"
    REFUSAL = "REFUSAL"
    NONE = "NONE"


LEDGER_LABELS = frozenset({Label.COMMITMENT, Label.HEDGED, Label.CONDITIONAL})


class Precision(StrEnum):
    DAY = "day"
    WEEK = "week"
    EVENT = "event"
    VAGUE = "vague"
    NONE = "none"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


# --- Request -------------------------------------------------------------------------------------


class Turn(Contract):
    speaker: str = Field(min_length=1, max_length=100, description="Speaker id or name.")
    text: str = Field(min_length=1, description="What the speaker said in this turn.")
    start_ms: int | None = Field(
        default=None, ge=0, description="Start of the turn in the audio; set for audio jobs."
    )
    end_ms: int | None = Field(
        default=None, ge=0, description="End of the turn in the audio; set for audio jobs."
    )

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("turn text must not be blank")
        return value

    @model_validator(mode="after")
    def _times_in_order(self) -> Self:
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms must not be before start_ms")
        return self


class UploadResponse(Contract):
    """A presigned S3 POST: send `fields`, then the file as the last form field, to `url`."""

    upload_id: str = Field(description="Names the upload in POST /jobs.")
    url: str
    fields: dict[str, str] = Field(description="Form fields to send before the file, unchanged.")
    max_bytes: int = Field(description="Largest accepted file; 60 s of 16 kHz mono 16-bit WAV.")
    expires_in: int = Field(description="Seconds the form stays valid.")


class JobRequest(Contract):
    """Starts a job from exactly one source: an upload, a sample clip or a typed transcript."""

    upload_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{32}$", description="From POST /uploads."
    )
    sample_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$", description="From GET /samples."
    )
    transcript: list[Turn] | None = Field(default=None, min_length=1, max_length=MAX_TURNS)
    call_date: date = Field(description="Date of the call; relative due dates resolve from it.")
    speaker_names: list[str] = Field(
        default_factory=list,
        max_length=2,
        description="Names for the first and second voice heard; audio sources only.",
    )

    @field_validator("speaker_names")
    @classmethod
    def _names_not_blank(cls, names: list[str]) -> list[str]:
        if any(_blank(name) or len(name) > 100 for name in names):
            raise ValueError("speaker names must be 1 to 100 characters")
        return names

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        sources = [self.upload_id, self.sample_id, self.transcript]
        if sum(source is not None for source in sources) != 1:
            raise ValueError("give exactly one of upload_id, sample_id and transcript")
        if self.transcript is not None:
            if self.speaker_names:
                raise ValueError("speaker_names applies to audio; a transcript names its speakers")
            if sum(len(turn.text) for turn in self.transcript) > MAX_TRANSCRIPT_CHARS:
                raise ValueError(f"transcript must be at most {MAX_TRANSCRIPT_CHARS} characters")
        return self


class FeedbackRequest(Contract):
    """A vote on one span of a finished job. The label and the text come from the job record."""

    job_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    span_index: int = Field(ge=0, le=999, description="Index into the job's analysis spans.")
    vote: Literal["up", "down"]
    consent: bool = Field(
        default=False,
        description="Keep the transcript and spans for up to 90 days to improve the labels.",
    )


class FeedbackResponse(Contract):
    transcript_kept: bool


class AnalyzeRequest(Contract):
    transcript: list[Turn] = Field(min_length=1, max_length=MAX_TURNS)
    call_date: date = Field(description="Date of the call; relative due dates resolve from it.")
    timezone: str | None = Field(
        default=None, max_length=64, description="IANA time zone of the call, if known."
    )

    @model_validator(mode="after")
    def _transcript_size(self) -> Self:
        if sum(len(turn.text) for turn in self.transcript) > MAX_TRANSCRIPT_CHARS:
            raise ValueError(f"transcript must be at most {MAX_TRANSCRIPT_CHARS} characters")
        return self


# --- Spans ---------------------------------------------------------------------------------------


class Due(Contract):
    raw: str | None = Field(
        min_length=1, description="The due phrase exactly as spoken, such as 'by Friday'."
    )
    resolved: date | None = Field(description="Calendar date resolved from call_date by code.")
    precision: Precision

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.resolved is not None and self.raw is None:
            raise ValueError("a resolved date needs the raw phrase it came from")
        if self.resolved is not None and self.precision not in {Precision.DAY, Precision.WEEK}:
            raise ValueError("a resolved date fits only day or week precision")
        if self.precision is Precision.NONE and self.raw is not None:
            raise ValueError("precision none means there is no raw phrase")
        if self.precision is not Precision.NONE and self.raw is None:
            raise ValueError("without a raw phrase the precision must be none")
        return self


class Span(Contract):
    turn_index: int = Field(ge=0, description="Index of the transcript turn the quote comes from.")
    label: Label
    owner: str | None = Field(description="Who is bound to act: a speaker id or a named person.")
    recipient: str | None = Field(description="Who the action is for.")
    action: str | None = Field(description="Short verb phrase, such as 'send revised pricing'.")
    due: Due
    condition: str | None = Field(description="The stated condition; required for CONDITIONAL.")
    confidence: float = Field(ge=0, le=1)
    quote: str = Field(min_length=1, description="Exact text from the turn.")
    rationale: str = Field(description="One-sentence explanation of the label.")
    ambiguous: bool

    @model_validator(mode="after")
    def _label_rules(self) -> Self:
        if self.label is Label.CONDITIONAL and _blank(self.condition):
            raise ValueError("condition is required when the label is CONDITIONAL")
        if self.label in LEDGER_LABELS and _blank(self.owner):
            raise ValueError(f"owner is required for ledger label {self.label}")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def in_ledger(self) -> bool:
        """COMMITMENT, HEDGED and CONDITIONAL create a ledger entry."""
        return self.label in LEDGER_LABELS

    @computed_field  # type: ignore[prop-decorator]
    @property
    def soft(self) -> bool:
        """HEDGED entries are stored in the ledger marked soft."""
        return self.label is Label.HEDGED


# --- Response ------------------------------------------------------------------------------------

Count = Annotated[int, Field(ge=0)]


class Metadata(Contract):
    model: str = Field(description="Model id the request asked for.")
    served_by: str = Field(description="Model that answered; differs after a refusal fallback.")
    prompt_version: str
    latency_ms: Count
    input_tokens: Count
    output_tokens: Count
    cache_creation_input_tokens: Count
    cache_read_input_tokens: Count
    cost_usd: Annotated[float, Field(ge=0)] | None = Field(
        description="Estimated cost; null when the model has no known price."
    )
    attempts: int = Field(ge=1, le=2, description="Model calls made: 2 after a validation retry.")
    dropped_quotes: Count = Field(description="Spans dropped because the quote was not found.")


class AnalyzeResponse(Contract):
    spans: list[Span]
    metadata: Metadata
