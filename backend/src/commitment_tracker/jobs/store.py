"""The job store boundary. Both implementations drop records once `expires_at` has passed."""

from typing import Protocol

from commitment_tracker.jobs.record import JobRecord, JobStatus, JobUpdate


class JobStore(Protocol):
    def create(self, job: JobRecord) -> JobRecord:
        """Store `job` and return that same object, or, when its id already exists, return the
        stored record (deduplication). Callers tell the two apart with `is`."""
        ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def transition(self, job_id: str, expected: JobStatus, update: JobUpdate) -> JobRecord | None:
        """Apply `update` only if the status is `expected`; None when it is not (or absent)."""
        ...
