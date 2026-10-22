"""A transcriber for tests and local runs: records started jobs and returns scripted turns."""

from collections.abc import Mapping, Sequence

from commitment_tracker.transcription.protocol import AudioRef, TimedTurn


class FakeTranscriber:
    def __init__(self, results: Mapping[str, Sequence[TimedTurn]] | None = None) -> None:
        self.results = {job_id: list(turns) for job_id, turns in (results or {}).items()}
        self.started: list[tuple[AudioRef, str]] = []

    def start(self, audio: AudioRef, job_id: str) -> None:
        self.started.append((audio, job_id))

    def result(self, job_id: str) -> list[TimedTurn]:
        if job_id not in self.results:
            raise LookupError(f"no scripted result for job {job_id}")
        return list(self.results[job_id])
