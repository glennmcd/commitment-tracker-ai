"""Span feedback: the stores (memory and DynamoDB stubs) and the service."""

import asyncio
import hashlib
import json
from collections.abc import Iterator
from datetime import date
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.feedback.dynamo import DynamoFeedbackStore, content_to_item
from commitment_tracker.feedback.service import (
    FeedbackService,
    FeedbackSpanNotFound,
    JobNotFinished,
    feedback_id_for,
)
from commitment_tracker.feedback.store import (
    CONTENT_TTL_SECONDS,
    ContentItem,
    FeedbackStore,
    MemoryFeedbackStore,
    VoteItem,
)
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.record import JobRecord, JobSource, JobStatus
from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse, FeedbackRequest, Turn
from tests.fakes import FakeAdapter, reply
from tests.test_api import GOOD_OUTPUT

NOW = 1_761_048_000.0
JOB_ID = "1" * 64
SECRET = "pricing-is-42"
TURNS = [
    Turn(speaker="A", text=f"Can you resend the invoice {SECRET}?"),
    Turn(speaker="B", text="Sure, I'll do it this afternoon."),
]
TABLE = "feedback"


def analysed() -> AnalyzeResponse:
    request = AnalyzeRequest(transcript=TURNS, call_date=date(2026, 10, 21))
    extractor = Extractor(FakeAdapter(reply(GOOD_OUTPUT)), load_prompt("v1"))
    return asyncio.run(extractor.analyze(request))


def done_job(**changes: Any) -> JobRecord:
    fields: dict[str, Any] = {
        "id": JOB_ID,
        "status": JobStatus.DONE,
        "source": JobSource.TRANSCRIPT,
        "call_date": date(2026, 10, 21),
        "turns": TURNS,
        "analysis": analysed(),
        "created_at": int(NOW * 1000),
        "expires_at": int(NOW) + 3600,
    }
    return JobRecord(**(fields | changes))


def request(**changes: Any) -> FeedbackRequest:
    fields: dict[str, Any] = {"job_id": JOB_ID, "span_index": 0, "vote": "up", "consent": False}
    return FeedbackRequest(**(fields | changes))


class Rig:
    def __init__(self, job: JobRecord | None = None) -> None:
        self.jobs = MemoryJobStore(clock=lambda: NOW)
        self.jobs.create(job or done_job())
        self.store = MemoryFeedbackStore()
        self.service = FeedbackService(self.jobs, self.store, clock=lambda: NOW)


# --- Service -------------------------------------------------------------------------------------


def test_a_vote_copies_the_label_from_the_job_not_from_the_client() -> None:
    rig = Rig()

    result = rig.service.submit(request(vote="down"))

    assert result.transcript_kept is False
    (vote,) = rig.store.votes.values()
    assert vote == VoteItem(
        job_id=JOB_ID,
        span_index=0,
        label="COMMITMENT",
        vote="down",
        feedback_id=feedback_id_for(JOB_ID, 0),
        voted_at=int(NOW),
    )
    assert rig.store.contents == {}


def test_a_vote_holds_no_text() -> None:
    rig = Rig()
    rig.service.submit(request())
    (vote,) = rig.store.votes.values()
    assert SECRET not in vote.model_dump_json()
    assert "afternoon" not in vote.model_dump_json()


def test_consent_also_keeps_the_transcript_and_spans_for_ninety_days() -> None:
    rig = Rig()

    result = rig.service.submit(request(consent=True))

    assert result.transcript_kept is True
    (content,) = rig.store.contents.values()
    job = done_job()
    assert content.feedback_id == feedback_id_for(JOB_ID, 0)
    assert content.job_id == JOB_ID
    assert content.transcript == TURNS
    assert content.spans == (job.analysis.spans if job.analysis else None)
    assert content.expires_at == int(NOW) + 90 * 86_400
    assert CONTENT_TTL_SECONDS == 90 * 86_400


def test_voting_again_replaces_the_vote() -> None:
    rig = Rig()
    rig.service.submit(request(vote="up"))
    rig.service.submit(request(vote="down"))
    (vote,) = rig.store.votes.values()
    assert vote.vote == "down"


def test_withdrawing_consent_deletes_the_kept_transcript() -> None:
    rig = Rig()
    rig.service.submit(request(consent=True))
    assert len(rig.store.contents) == 1

    rig.service.submit(request(consent=False))

    assert rig.store.contents == {}
    assert len(rig.store.votes) == 1


def test_the_feedback_id_depends_on_job_and_span() -> None:
    assert feedback_id_for(JOB_ID, 0) == feedback_id_for(JOB_ID, 0)
    assert feedback_id_for(JOB_ID, 0) != feedback_id_for(JOB_ID, 1)
    assert feedback_id_for(JOB_ID, 0) != feedback_id_for("2" * 64, 0)
    assert feedback_id_for(JOB_ID, 0) == hashlib.sha256(f"{JOB_ID}#0".encode()).hexdigest()[:32]


def test_an_unknown_job_is_not_found() -> None:
    with pytest.raises(LookupError):
        Rig().service.submit(request(job_id="2" * 64))


@pytest.mark.parametrize("status", [JobStatus.TRANSCRIBING, JobStatus.ANALYZING, JobStatus.FAILED])
def test_a_job_that_is_not_done_takes_no_feedback(status: JobStatus) -> None:
    rig = Rig(done_job(status=status, analysis=None))
    with pytest.raises(JobNotFinished):
        rig.service.submit(request())
    assert rig.store.votes == {}


@pytest.mark.parametrize("index", [1, 50])
def test_a_span_that_does_not_exist_takes_no_feedback(index: int) -> None:
    rig = Rig()
    with pytest.raises(FeedbackSpanNotFound):
        rig.service.submit(request(span_index=index))
    assert rig.store.votes == {}


# --- Request -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"vote": "meh"},
        {"span_index": -1},
        {"span_index": 10_000},
        {"job_id": "short"},
        {"job_id": "G" * 64},
        {"label": "NONE"},
        {"transcript": "anything"},
    ],
)
def test_invalid_feedback_requests_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic's ValidationError is a ValueError
        request(**changes)


# --- DynamoDB store ------------------------------------------------------------------------------


@pytest.fixture
def dynamo() -> Iterator[tuple[DynamoFeedbackStore, Stubber]]:
    client = boto3.client(
        "dynamodb",
        region_name="us-east-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with Stubber(client) as stub:
        yield DynamoFeedbackStore(client, TABLE), stub
        stub.assert_no_pending_responses()


def test_dynamo_stores_a_vote_without_a_ttl(dynamo: tuple[DynamoFeedbackStore, Stubber]) -> None:
    store, stub = dynamo
    fid = feedback_id_for(JOB_ID, 0)
    stub.add_response(
        "put_item",
        {},
        {
            "TableName": TABLE,
            "Item": {
                "pk": {"S": f"vote#{JOB_ID}#0"},
                "job_id": {"S": JOB_ID},
                "span_index": {"N": "0"},
                "label": {"S": "COMMITMENT"},
                "vote": {"S": "up"},
                "feedback_id": {"S": fid},
                "voted_at": {"N": str(int(NOW))},
            },
        },
    )

    store.put_vote(
        VoteItem(
            job_id=JOB_ID,
            span_index=0,
            label="COMMITMENT",
            vote="up",
            feedback_id=fid,
            voted_at=int(NOW),
        )
    )


def test_dynamo_stores_content_with_a_ttl_and_deletes_it(
    dynamo: tuple[DynamoFeedbackStore, Stubber],
) -> None:
    store, stub = dynamo
    job = done_job()
    assert job.analysis is not None
    item = ContentItem(
        feedback_id="f" * 32,
        job_id=JOB_ID,
        transcript=TURNS,
        spans=job.analysis.spans,
        expires_at=int(NOW) + CONTENT_TTL_SECONDS,
    )
    stored = content_to_item(item)
    stub.add_response("put_item", {}, {"TableName": TABLE, "Item": stored})
    stub.add_response(
        "delete_item", {}, {"TableName": TABLE, "Key": {"pk": {"S": f"content#{'f' * 32}"}}}
    )

    store.put_content(item)
    store.delete_content("f" * 32)

    assert stored["pk"] == {"S": f"content#{'f' * 32}"}
    assert stored["expires_at"] == {"N": str(item.expires_at)}
    record = json.loads(stored["record"]["S"])
    assert record["transcript"][1]["text"] == "Sure, I'll do it this afternoon."
    assert record["spans"][0]["label"] == "COMMITMENT"


def test_all_stores_satisfy_the_protocol() -> None:
    stores: list[FeedbackStore] = [MemoryFeedbackStore()]
    assert stores
