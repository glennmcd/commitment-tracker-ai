"""A job store for tests and local runs."""

import time
from collections.abc import Callable

from commitment_tracker.jobs.record import JobRecord, JobStatus, JobUpdate


class MemoryJobStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._jobs: dict[str, JobRecord] = {}

    def _live(self, job_id: str) -> JobRecord | None:
        job = self._jobs.get(job_id)
        if job is not None and job.expires_at <= self._clock():
            del self._jobs[job_id]
            return None
        return job

    def create(self, job: JobRecord) -> JobRecord:
        existing = self._live(job.id)
        if existing is not None:
            return existing
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self._live(job_id)

    def transition(self, job_id: str, expected: JobStatus, update: JobUpdate) -> JobRecord | None:
        job = self._live(job_id)
        if job is None or job.status is not expected:
            return None
        updated = job.apply(update)
        self._jobs[job_id] = updated
        return updated
