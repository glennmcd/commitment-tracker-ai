"""POST /feedback through the TestClient, on fakes."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from commitment_tracker.api.app import create_app
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.feedback.service import FeedbackService
from commitment_tracker.feedback.store import MemoryFeedbackStore
from commitment_tracker.guardrails.ratelimit import Limit, MemoryRateLimitStore, RateLimiter
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.record import JobStatus, JobUpdate
from tests.fakes import FakeAdapter
from tests.test_feedback import JOB_ID, NOW, SECRET, done_job

BODY: dict[str, Any] = {"job_id": JOB_ID, "span_index": 0, "vote": "up", "consent": False}


class Rig:
    def __init__(self, *, with_service: bool = True, limiter: RateLimiter | None = None) -> None:
        self.jobs = MemoryJobStore(clock=lambda: NOW)
        self.jobs.create(done_job())
        self.store = MemoryFeedbackStore()
        service = FeedbackService(self.jobs, self.store, clock=lambda: NOW)
        extractor = Extractor(FakeAdapter(), load_prompt("v1"))
        self.client = TestClient(
            create_app(
                extractor=extractor,
                feedback=service if with_service else None,
                limiter=limiter,
            )
        )


def test_a_vote_is_stored() -> None:
    rig = Rig()

    response = rig.client.post("/feedback", json=BODY)

    assert response.status_code == 200
    assert response.json() == {"transcript_kept": False}
    (vote,) = rig.store.votes.values()
    assert (vote.label, vote.vote) == ("COMMITMENT", "up")


def test_consent_keeps_the_transcript_and_says_so() -> None:
    rig = Rig()

    response = rig.client.post("/feedback", json=BODY | {"consent": True})

    assert response.json() == {"transcript_kept": True}
    assert len(rig.store.contents) == 1


def test_consent_defaults_to_no() -> None:
    rig = Rig()
    body = {k: v for k, v in BODY.items() if k != "consent"}

    assert rig.client.post("/feedback", json=body).json() == {"transcript_kept": False}
    assert rig.store.contents == {}


@pytest.mark.parametrize(
    "body",
    [
        BODY | {"label": "NONE"},
        BODY | {"vote": "sideways"},
        BODY | {"span_index": -1},
        BODY | {"job_id": "../x"},
        BODY | {"transcript": SECRET},
        {k: v for k, v in BODY.items() if k != "vote"},
    ],
    ids=["client-label", "bad-vote", "negative-index", "bad-id", "client-transcript", "no-vote"],
)
def test_invalid_feedback_gets_422_without_echoing_input(body: dict[str, Any]) -> None:
    rig = Rig()

    response = rig.client.post("/feedback", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert SECRET not in response.text
    assert rig.store.votes == {}


def test_an_unknown_job_is_404() -> None:
    response = Rig().client.post("/feedback", json=BODY | {"job_id": "2" * 64})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_a_job_that_is_not_done_is_409() -> None:
    rig = Rig()
    rig.jobs.transition(JOB_ID, JobStatus.DONE, JobUpdate(status=JobStatus.FAILED, error_code="x"))

    response = rig.client.post("/feedback", json=BODY)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_finished"


def test_a_span_that_does_not_exist_is_404() -> None:
    response = Rig().client.post("/feedback", json=BODY | {"span_index": 9})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "span_not_found"


def test_without_a_feedback_store_the_route_is_503() -> None:
    response = Rig(with_service=False).client.post("/feedback", json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "jobs_unavailable"


def test_feedback_is_rate_limited() -> None:
    limiter = RateLimiter(
        MemoryRateLimitStore(), {"feedback": Limit(max=1, window_seconds=60)}, clock=lambda: NOW
    )
    rig = Rig(limiter=limiter)

    codes = [rig.client.post("/feedback", json=BODY).status_code for _ in range(2)]

    assert codes == [200, 429]


def test_feedback_logs_no_transcript_text(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    with caplog.at_level(logging.DEBUG):
        rig.client.post("/feedback", json=BODY | {"consent": True})
    assert SECRET not in caplog.text
    assert "afternoon" not in caplog.text
