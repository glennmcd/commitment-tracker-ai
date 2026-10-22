"""The transcription boundary: start a job on stored audio, later read its turns.

Jobs are asynchronous: `start` returns once the job is submitted, and the worker calls `result`
when the service reports the job finished. Speakers are numbered in order of first speech; the
visitor's names are applied afterwards by `turns.name_turns`.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioRef:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


@dataclass(frozen=True)
class TimedTurn:
    speaker: int  # 0 for the first voice heard, 1 for the next, ...
    text: str
    start_ms: int
    end_ms: int


class Transcriber(Protocol):
    def start(self, audio: AudioRef, job_id: str) -> None: ...

    def result(self, job_id: str) -> list[TimedTurn]: ...
