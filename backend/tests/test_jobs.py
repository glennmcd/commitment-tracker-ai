"""The job record, the in-memory store and the DynamoDB store (on botocore stubs, no network)."""

from collections.abc import Iterator
from datetime import date
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from pydantic import ValidationError

from commitment_tracker.jobs.dynamo import DynamoJobStore
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.record import (
    JobRecord,
    JobSource,
    JobStatus,
    JobUpdate,
    Latency,
)
from commitment_tracker.jobs.store import JobStore
from commitment_tracker.schemas import AnalyzeResponse, Metadata, Turn

NOW = 1_000_000  # epoch seconds
TABLE = "jobs"


def analysis() -> AnalyzeResponse:
    metadata = Metadata(
        model="m",
        served_by="m",
        prompt_version="v1",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        cost_usd=0.001,
        attempts=1,
        dropped_quotes=0,
    )
    return AnalyzeResponse(spans=[], metadata=metadata)


def make_job(job_id: str = "abc", **changes: Any) -> JobRecord:
    fields: dict[str, Any] = {
        "id": job_id,
        "status": JobStatus.TRANSCRIBING,
        "source": JobSource.UPLOAD,
        "audio_key": f"uploads/{job_id}.wav",
        "call_date": date(2026, 10, 21),
        "speaker_names": ["Ana", "Ben"],
        "created_at": NOW * 1000,
        "expires_at": NOW + 3600,
    }
    return JobRecord(**(fields | changes))


# --- Record ----------------------------------------------------------------------------------


def test_record_round_trips_through_json() -> None:
    job = make_job(
        turns=[Turn(speaker="Ana", text="Hello.", start_ms=0, end_ms=400)], analysis=analysis()
    )

    assert JobRecord.model_validate_json(job.model_dump_json()) == job


def test_record_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        make_job(status="stuck")


def test_validation_errors_hide_the_transcript() -> None:
    with pytest.raises(ValidationError) as caught:
        make_job(turns=[{"speaker": "Ana", "text": "secret words", "start_ms": -1}])

    assert "secret words" not in str(caught.value)


def test_apply_changes_only_the_fields_that_were_set() -> None:
    job = make_job(error_code="x")

    updated = job.apply(JobUpdate(status=JobStatus.ANALYZING, analyzing_at=5))

    assert updated.status is JobStatus.ANALYZING
    assert updated.analyzing_at == 5
    assert updated.error_code == "x"
    assert updated.audio_key == job.audio_key


def test_apply_can_set_a_field_back_to_none() -> None:
    job = make_job(error_code="x")

    assert job.apply(JobUpdate(status=JobStatus.DONE, error_code=None)).error_code is None


def test_latency_of_a_finished_upload_job() -> None:
    job = make_job(
        upload_started_at=900,
        created_at=1_000,
        transcribing_at=1_100,
        transcribed_at=16_500,
        analyzing_at=16_600,
        finished_at=18_000,
    )

    assert job.latency() == Latency(
        upload_ms=100, transcribe_ms=15_400, analyze_ms=1_400, total_ms=17_000
    )


def test_latency_is_none_for_stages_not_reached() -> None:
    job = make_job(created_at=1_000, transcribing_at=1_100)

    assert job.latency() == Latency()


def test_latency_of_a_text_job_has_no_upload_or_transcribe() -> None:
    job = make_job(
        source=JobSource.TRANSCRIPT,
        audio_key=None,
        created_at=1_000,
        analyzing_at=1_050,
        finished_at=1_800,
    )

    assert job.latency() == Latency(analyze_ms=750, total_ms=800)


# --- In-memory store -------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = float(NOW)

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def test_memory_store_satisfies_the_protocol(clock: Clock) -> None:
    store: JobStore = MemoryJobStore(clock)
    assert isinstance(store, MemoryJobStore)


def test_memory_create_then_get(clock: Clock) -> None:
    store = MemoryJobStore(clock)
    job = make_job()

    assert store.create(job) == job
    assert store.get("abc") == job


def test_memory_duplicate_create_returns_the_original(clock: Clock) -> None:
    store = MemoryJobStore(clock)
    first = store.create(make_job())

    again = store.create(make_job(status=JobStatus.DONE))

    assert again == first
    assert store.get("abc") == first


def test_memory_unknown_job_is_none(clock: Clock) -> None:
    assert MemoryJobStore(clock).get("nope") is None


def test_memory_expired_job_is_gone_and_can_be_recreated(clock: Clock) -> None:
    store = MemoryJobStore(clock)
    store.create(make_job())
    clock.now = NOW + 3600

    assert store.get("abc") is None
    fresh = make_job(expires_at=NOW + 7200)
    assert store.create(fresh) == fresh


def test_memory_transition_applies_when_the_status_matches(clock: Clock) -> None:
    store = MemoryJobStore(clock)
    store.create(make_job())

    updated = store.transition(
        "abc", JobStatus.TRANSCRIBING, JobUpdate(status=JobStatus.ANALYZING, transcribed_at=7)
    )

    assert updated is not None
    assert updated.status is JobStatus.ANALYZING
    assert store.get("abc") == updated


def test_memory_transition_refuses_the_wrong_status_and_leaves_the_job(clock: Clock) -> None:
    store = MemoryJobStore(clock)
    job = store.create(make_job())

    assert store.transition("abc", JobStatus.ANALYZING, JobUpdate(status=JobStatus.DONE)) is None
    assert store.get("abc") == job


def test_memory_a_second_transition_from_the_same_status_loses(clock: Clock) -> None:
    store = MemoryJobStore(clock)
    store.create(make_job())
    move = JobUpdate(status=JobStatus.ANALYZING)

    assert store.transition("abc", JobStatus.TRANSCRIBING, move) is not None
    assert store.transition("abc", JobStatus.TRANSCRIBING, move) is None


def test_memory_transition_of_an_unknown_job_is_none(clock: Clock) -> None:
    update = JobUpdate(status=JobStatus.DONE)
    assert MemoryJobStore(clock).transition("nope", JobStatus.TRANSCRIBING, update) is None


# --- DynamoDB store --------------------------------------------------------------------------


class Rig:
    def __init__(self, clock: Clock) -> None:
        self.client = boto3.client(
            "dynamodb",
            region_name="us-east-2",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        self.stub = Stubber(self.client)
        self.store = DynamoJobStore(self.client, TABLE, clock)


@pytest.fixture
def rig(clock: Clock) -> Iterator[Rig]:
    rig = Rig(clock)
    with rig.stub:
        yield rig
        rig.stub.assert_no_pending_responses()


def item(job: JobRecord) -> dict[str, Any]:
    return {
        "id": {"S": job.id},
        "status": {"S": job.status.value},
        "expires_at": {"N": str(job.expires_at)},
        "record": {"S": job.model_dump_json()},
    }


def get_params(job_id: str = "abc") -> dict[str, Any]:
    return {"TableName": TABLE, "Key": {"id": {"S": job_id}}, "ConsistentRead": True}


def test_dynamo_create_writes_a_conditional_item(rig: Rig) -> None:
    job = make_job()
    rig.stub.add_response(
        "put_item",
        {},
        {
            "TableName": TABLE,
            "Item": item(job),
            "ConditionExpression": "attribute_not_exists(id) OR expires_at <= :now",
            "ExpressionAttributeValues": {":now": {"N": str(NOW)}},
        },
    )

    assert rig.store.create(job) == job


def test_dynamo_duplicate_create_returns_the_stored_job(rig: Rig) -> None:
    stored = make_job(status=JobStatus.DONE)
    rig.stub.add_client_error("put_item", "ConditionalCheckFailedException")
    rig.stub.add_response("get_item", {"Item": item(stored)}, get_params())

    assert rig.store.create(make_job()) == stored


def test_dynamo_create_raises_other_errors(rig: Rig) -> None:
    rig.stub.add_client_error("put_item", "ProvisionedThroughputExceededException")

    with pytest.raises(Exception, match="ProvisionedThroughputExceededException"):
        rig.store.create(make_job())


def test_dynamo_get_reads_consistently(rig: Rig) -> None:
    job = make_job()
    rig.stub.add_response("get_item", {"Item": item(job)}, get_params())

    assert rig.store.get("abc") == job


def test_dynamo_get_unknown_is_none(rig: Rig) -> None:
    rig.stub.add_response("get_item", {}, get_params("nope"))

    assert rig.store.get("nope") is None


def test_dynamo_get_ignores_an_expired_item_awaiting_ttl_deletion(rig: Rig, clock: Clock) -> None:
    rig.stub.add_response("get_item", {"Item": item(make_job())}, get_params())
    clock.now = NOW + 3600

    assert rig.store.get("abc") is None


def test_dynamo_transition_is_conditional_on_status_and_the_record_read(rig: Rig) -> None:
    job = make_job()
    update = JobUpdate(status=JobStatus.ANALYZING, transcribed_at=7)
    updated = job.apply(update)
    rig.stub.add_response("get_item", {"Item": item(job)}, get_params())
    rig.stub.add_response(
        "put_item",
        {},
        {
            "TableName": TABLE,
            "Item": item(updated),
            "ConditionExpression": "#status = :expected AND #record = :previous",
            "ExpressionAttributeNames": {"#status": "status", "#record": "record"},
            "ExpressionAttributeValues": {
                ":expected": {"S": "transcribing"},
                ":previous": {"S": job.model_dump_json()},
            },
        },
    )

    assert rig.store.transition("abc", JobStatus.TRANSCRIBING, update) == updated


def test_dynamo_transition_from_another_status_writes_nothing(rig: Rig) -> None:
    rig.stub.add_response("get_item", {"Item": item(make_job(status=JobStatus.DONE))}, get_params())

    result = rig.store.transition(
        "abc", JobStatus.TRANSCRIBING, JobUpdate(status=JobStatus.ANALYZING)
    )

    assert result is None


def test_dynamo_transition_of_an_unknown_job_writes_nothing(rig: Rig) -> None:
    rig.stub.add_response("get_item", {}, get_params())

    assert (
        rig.store.transition("abc", JobStatus.TRANSCRIBING, JobUpdate(status=JobStatus.DONE))
        is None
    )


def test_dynamo_transition_that_loses_a_race_returns_none(rig: Rig) -> None:
    rig.stub.add_response("get_item", {"Item": item(make_job())}, get_params())
    rig.stub.add_client_error("put_item", "ConditionalCheckFailedException")

    result = rig.store.transition(
        "abc", JobStatus.TRANSCRIBING, JobUpdate(status=JobStatus.ANALYZING)
    )

    assert result is None


def test_dynamo_transition_raises_other_errors(rig: Rig) -> None:
    rig.stub.add_response("get_item", {"Item": item(make_job())}, get_params())
    rig.stub.add_client_error("put_item", "InternalServerError")

    with pytest.raises(Exception, match="InternalServerError"):
        rig.store.transition("abc", JobStatus.TRANSCRIBING, JobUpdate(status=JobStatus.ANALYZING))
