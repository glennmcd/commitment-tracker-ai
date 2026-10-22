"""Recording feedback on a finished job's spans.

The client names a job and a span index; the label, transcript and spans all come from the job
record, so the endpoint can't be used to store arbitrary text. Consent decides whether the
transcript is kept alongside the vote, and voting again without consent deletes what was kept.
Logs carry the vote, the label and whether a transcript was kept, never the text.
"""

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from commitment_tracker.feedback.store import (
    CONTENT_TTL_SECONDS,
    ContentItem,
    FeedbackStore,
    VoteItem,
)
from commitment_tracker.jobs.record import JobStatus
from commitment_tracker.jobs.store import JobStore
from commitment_tracker.schemas import FeedbackRequest

logger = logging.getLogger(__name__)


class FeedbackJobNotFound(LookupError):
    pass


class JobNotFinished(Exception):
    pass


class FeedbackSpanNotFound(LookupError):
    pass


@dataclass(frozen=True)
class FeedbackResult:
    transcript_kept: bool


def feedback_id_for(job_id: str, span_index: int) -> str:
    """The same for every vote on a span, so a second vote replaces the first and its content."""
    return hashlib.sha256(f"{job_id}#{span_index}".encode()).hexdigest()[:32]


class FeedbackService:
    def __init__(
        self,
        jobs: JobStore,
        store: FeedbackStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._jobs = jobs
        self._store = store
        self._clock = clock

    def submit(self, request: FeedbackRequest) -> FeedbackResult:
        job = self._jobs.get(request.job_id)
        if job is None:
            raise FeedbackJobNotFound(request.job_id)
        if job.status is not JobStatus.DONE or job.analysis is None or job.turns is None:
            raise JobNotFinished(request.job_id)
        if request.span_index >= len(job.analysis.spans):
            raise FeedbackSpanNotFound(request.job_id)

        now = int(self._clock())
        feedback_id = feedback_id_for(request.job_id, request.span_index)
        label = job.analysis.spans[request.span_index].label.value
        if request.consent:
            self._store.put_content(
                ContentItem(
                    feedback_id=feedback_id,
                    job_id=job.id,
                    transcript=job.turns,
                    spans=job.analysis.spans,
                    expires_at=now + CONTENT_TTL_SECONDS,
                )
            )
        else:
            self._store.delete_content(feedback_id)
        self._store.put_vote(
            VoteItem(
                job_id=job.id,
                span_index=request.span_index,
                label=label,
                vote=request.vote,
                feedback_id=feedback_id,
                voted_at=now,
            )
        )
        logger.info(
            "feedback stored vote=%s label=%s transcript_kept=%s",
            request.vote,
            label,
            request.consent,
        )
        return FeedbackResult(transcript_kept=request.consent)
