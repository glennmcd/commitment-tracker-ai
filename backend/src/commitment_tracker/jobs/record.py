"""The job record and its stage latencies.

A record lives in the store until its TTL removes it; it is the only place a transcript is kept.
Times are epoch milliseconds, `expires_at` is epoch seconds (DynamoDB's TTL unit). Validation
errors never include the transcript text.
"""

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from commitment_tracker.schemas import AnalyzeResponse, Turn

JOB_TTL_SECONDS = 3600


class JobStatus(StrEnum):
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    DONE = "done"
    FAILED = "failed"


class JobSource(StrEnum):
    UPLOAD = "upload"
    SAMPLE = "sample"
    TRANSCRIPT = "transcript"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Latency(_Model):
    upload_ms: int | None = None
    transcribe_ms: int | None = None
    analyze_ms: int | None = None
    total_ms: int | None = None


class JobUpdate(_Model):
    """Fields a transition changes; the status is always set, the rest only when given."""

    status: JobStatus
    turns: list[Turn] | None = None
    analysis: AnalyzeResponse | None = None
    error_code: str | None = Field(default=None, min_length=1)
    transcribing_at: int | None = Field(default=None, ge=0)
    transcribed_at: int | None = Field(default=None, ge=0)
    analyzing_at: int | None = Field(default=None, ge=0)
    finished_at: int | None = Field(default=None, ge=0)


class JobRecord(_Model):
    id: str = Field(min_length=1)
    status: JobStatus
    source: JobSource
    audio_key: str | None = None  # None for text jobs
    call_date: date
    speaker_names: list[str] = Field(default_factory=list)
    turns: list[Turn] | None = None
    analysis: AnalyzeResponse | None = None
    error_code: str | None = None
    upload_started_at: int | None = Field(default=None, ge=0)  # when the upload was presigned
    created_at: int = Field(ge=0)
    transcribing_at: int | None = Field(default=None, ge=0)
    transcribed_at: int | None = Field(default=None, ge=0)  # the Transcribe event arrived
    analyzing_at: int | None = Field(default=None, ge=0)
    finished_at: int | None = Field(default=None, ge=0)  # done or failed
    expires_at: int = Field(ge=0)

    def apply(self, update: JobUpdate) -> "JobRecord":
        """The record with the fields `update` sets; the result is validated again."""
        data = self._data() | {name: getattr(update, name) for name in update.model_fields_set}
        return JobRecord.model_validate(data)

    def _data(self) -> dict[str, Any]:
        # Spans dump computed fields (in_ledger, soft) that their own validation forbids as input.
        return self.model_dump(exclude_computed_fields=True)

    def to_json(self) -> str:
        """The form stored in a job store; `model_validate_json` reads it back."""
        return self.model_dump_json(exclude_computed_fields=True)

    def latency(self) -> Latency:
        return Latency(
            upload_ms=_between(self.upload_started_at, self.created_at),
            transcribe_ms=_between(self.transcribing_at, self.transcribed_at),
            analyze_ms=_between(self.analyzing_at, self.finished_at),
            total_ms=_between(self.created_at, self.finished_at),
        )


def _between(start: int | None, end: int | None) -> int | None:
    if start is None or end is None:
        return None
    return max(end - start, 0)
