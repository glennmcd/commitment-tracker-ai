"""The Lambda entry points: SSM settings, the Mangum API handler and the worker handler."""

import json
import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from pydantic import SecretStr

from commitment_tracker.api.app import build_job_service, create_app
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.guardrails.ratelimit import Limit, MemoryRateLimitStore, RateLimiter
from commitment_tracker.jobs.dispatch import ANALYZE_TEXT, LambdaWorkerDispatcher
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.record import JobRecord, JobSource, JobStatus
from commitment_tracker.jobs.service import TextJobsUnavailable
from commitment_tracker.jobs.worker import JobWorker
from commitment_tracker.lambda_handlers import (
    build_worker,
    load_settings,
    make_api_handler,
    make_worker_handler,
)
from commitment_tracker.schemas import Turn
from commitment_tracker.settings import Settings
from commitment_tracker.transcription.fake import FakeTranscriber
from tests.fakes import FakeAdapter, FakeAudioStore, reply
from tests.test_api import GOOD_OUTPUT
from tests.test_job_worker import JOB_ID, NOW, TIMED, make_job, text_job

PARAMETER = "/commitment-tracker/prod/ANTHROPIC_API_KEY"
KEY_VALUE = "sk-ant-not-a-real-key"


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


# --- SSM settings --------------------------------------------------------------------------------


@pytest.fixture
def ssm() -> Iterator[tuple[Any, Stubber]]:
    client = boto3.client(
        "ssm", region_name="us-east-2", aws_access_key_id="test", aws_secret_access_key="test"
    )
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def test_the_api_key_is_read_from_the_named_parameter(ssm: tuple[Any, Stubber]) -> None:
    client, stub = ssm
    stub.add_response(
        "get_parameter",
        {"Parameter": {"Name": PARAMETER, "Value": KEY_VALUE}},
        {"Name": PARAMETER, "WithDecryption": True},
    )

    loaded = load_settings(settings(anthropic_api_key_parameter=PARAMETER), ssm=client)

    assert isinstance(loaded.anthropic_api_key, SecretStr)
    assert loaded.anthropic_api_key.get_secret_value() == KEY_VALUE
    assert KEY_VALUE not in repr(loaded)


def test_a_key_already_in_the_environment_is_not_fetched(ssm: tuple[Any, Stubber]) -> None:
    client, _ = ssm  # no response queued: any call would fail
    given = settings(anthropic_api_key="sk-ant-from-env", anthropic_api_key_parameter=PARAMETER)

    assert load_settings(given, ssm=client) is given


def test_with_no_parameter_configured_nothing_is_fetched(ssm: tuple[Any, Stubber]) -> None:
    client, _ = ssm
    assert load_settings(settings(), ssm=client).anthropic_api_key is None


def test_a_missing_parameter_names_the_parameter_not_a_value(ssm: tuple[Any, Stubber]) -> None:
    client, stub = ssm
    stub.add_client_error("get_parameter", "ParameterNotFound")

    with pytest.raises(RuntimeError, match=PARAMETER):
        load_settings(settings(anthropic_api_key_parameter=PARAMETER), ssm=client)


def test_the_key_is_never_logged(
    ssm: tuple[Any, Stubber], caplog: pytest.LogCaptureFixture
) -> None:
    client, stub = ssm
    stub.add_response("get_parameter", {"Parameter": {"Name": PARAMETER, "Value": KEY_VALUE}})

    with caplog.at_level(logging.DEBUG):
        load_settings(settings(anthropic_api_key_parameter=PARAMETER), ssm=client)

    assert KEY_VALUE not in caplog.text


# --- API handler ---------------------------------------------------------------------------------


def http_event(
    path: str, method: str = "GET", ip: str = "203.0.113.7", **headers: str
) -> dict[str, Any]:
    """An API Gateway HTTP API (payload 2.0) event, as the gateway sends it."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": "api.example.com", "content-type": "application/json", **headers},
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "abc123",
            "domainName": "api.example.com",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": ip,
                "userAgent": "test",
            },
            "requestId": "r1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "22/Oct/2026:13:00:00 +0000",
            "timeEpoch": 1_761_137_200_000,
        },
        "isBase64Encoded": False,
    }


def api_handler(**kwargs: Any) -> Any:
    extractor = Extractor(FakeAdapter(), load_prompt("v1"))
    return make_api_handler(create_app(extractor=extractor, **kwargs))


def test_the_api_answers_an_api_gateway_event() -> None:
    response = api_handler()(http_event("/health"), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "ok"


def test_the_client_is_the_gateways_source_ip_not_x_forwarded_for() -> None:
    limit = {"uploads": Limit(max=1, window_seconds=3600)}
    limiter = RateLimiter(MemoryRateLimitStore(), limit, clock=lambda: NOW)
    handler = api_handler(limiter=limiter)

    first = handler(http_event("/uploads", "POST", **{"x-forwarded-for": "1.1.1.1"}), None)
    second = handler(http_event("/uploads", "POST", **{"x-forwarded-for": "2.2.2.2"}), None)
    other_client = handler(http_event("/uploads", "POST", ip="198.51.100.9"), None)

    assert first["statusCode"] == 503  # past the limiter; no bucket is configured
    assert second["statusCode"] == 429
    assert other_client["statusCode"] == 503


# --- Worker handler ------------------------------------------------------------------------------


class WorkerRig:
    def __init__(self, job: JobRecord | None = None) -> None:
        self.store = MemoryJobStore(clock=lambda: NOW)
        self.store.create(job or make_job())
        self.audio = FakeAudioStore()
        self.adapter = FakeAdapter(reply(GOOD_OUTPUT))
        worker = JobWorker(
            self.store,
            self.audio,
            FakeTranscriber({JOB_ID: TIMED}),
            Extractor(self.adapter, load_prompt("v1")),
            clock=lambda: NOW,
        )
        self.handler = make_worker_handler(worker)


def transcribe_event(status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "source": "aws.transcribe",
        "detail-type": "Transcribe Job State Change",
        "detail": {"TranscriptionJobName": f"ct-{JOB_ID}", "TranscriptionJobStatus": status},
    }


def test_a_transcribe_event_finishes_the_job() -> None:
    rig = WorkerRig()

    rig.handler(transcribe_event(), None)

    job = rig.store.get(JOB_ID)
    assert job is not None
    assert job.status is JobStatus.DONE


def test_a_failed_transcribe_event_fails_the_job() -> None:
    rig = WorkerRig()

    rig.handler(transcribe_event("FAILED"), None)

    job = rig.store.get(JOB_ID)
    assert job is not None
    assert (job.status, job.error_code) == (JobStatus.FAILED, "transcription_failed")


def test_a_direct_invoke_runs_a_text_job() -> None:
    rig = WorkerRig(text_job())

    rig.handler({"action": ANALYZE_TEXT, "job_id": JOB_ID}, None)

    job = rig.store.get(JOB_ID)
    assert job is not None
    assert (job.status, job.source) == (JobStatus.DONE, JobSource.TRANSCRIPT)


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"action": "something-else", "job_id": JOB_ID},
        {"action": ANALYZE_TEXT},
        {"action": ANALYZE_TEXT, "job_id": "short"},
        {"source": "aws.transcribe", "detail": {"TranscriptionJobName": "other"}},
        "not a mapping",
    ],
    ids=["empty", "unknown-action", "no-job-id", "bad-job-id", "foreign-job", "not-a-mapping"],
)
def test_other_events_are_ignored(event: Any) -> None:
    rig = WorkerRig()

    rig.handler(event, None)

    assert rig.adapter.requests == []
    job = rig.store.get(JOB_ID)
    assert job is not None
    assert job.status is JobStatus.TRANSCRIBING


# --- Wiring from settings ------------------------------------------------------------------------


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")


@pytest.mark.usefixtures("aws_env")
def test_the_worker_is_built_from_its_environment() -> None:
    worker = build_worker(
        settings(jobs_table="jobs", audio_bucket="audio", anthropic_api_key="sk-ant-test")
    )
    assert isinstance(worker, JobWorker)


@pytest.mark.parametrize(
    ("given", "named"),
    [
        ({}, "JOBS_TABLE and AUDIO_BUCKET"),
        ({"jobs_table": "jobs"}, "AUDIO_BUCKET"),
        ({"audio_bucket": "audio"}, "JOBS_TABLE"),
    ],
)
def test_a_worker_without_its_environment_says_what_is_missing(
    given: dict[str, str], named: str
) -> None:
    with pytest.raises(RuntimeError, match=named):
        build_worker(settings(**given))


@pytest.mark.usefixtures("aws_env")
def test_text_jobs_get_a_dispatcher_only_when_the_worker_is_named() -> None:
    base = {"jobs_table": "jobs", "audio_bucket": "audio"}

    without = build_job_service(settings(**base))
    with_worker = build_job_service(settings(**base, worker_function_name="worker"))

    assert without is not None and with_worker is not None
    with pytest.raises(TextJobsUnavailable):
        without.start_text([Turn(speaker="A", text="Hi.")], date(2026, 10, 21))
    assert isinstance(with_worker._dispatcher, LambdaWorkerDispatcher)  # noqa: SLF001


def test_no_job_service_without_a_bucket_and_table() -> None:
    assert build_job_service(settings()) is None
