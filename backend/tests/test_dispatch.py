"""LambdaWorkerDispatcher against a botocore-stubbed Lambda client."""

import json
from collections.abc import Iterator

import boto3
import pytest
from botocore.stub import Stubber

from commitment_tracker.jobs.dispatch import ANALYZE_TEXT, LambdaWorkerDispatcher
from commitment_tracker.jobs.service import WorkerDispatcher

JOB_ID = "1" * 64
FUNCTION = "commitment-tracker-worker"


@pytest.fixture
def rig() -> Iterator[tuple[LambdaWorkerDispatcher, Stubber]]:
    client = boto3.client(
        "lambda",
        region_name="us-east-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with Stubber(client) as stub:
        yield LambdaWorkerDispatcher(client, FUNCTION), stub
        stub.assert_no_pending_responses()


def test_it_invokes_the_worker_asynchronously_with_the_job_id(
    rig: tuple[LambdaWorkerDispatcher, Stubber],
) -> None:
    dispatcher, stub = rig
    payload = json.dumps({"action": ANALYZE_TEXT, "job_id": JOB_ID}, separators=(",", ":"))
    stub.add_response(
        "invoke",
        {"StatusCode": 202},
        {"FunctionName": FUNCTION, "InvocationType": "Event", "Payload": payload.encode()},
    )

    dispatcher.dispatch(JOB_ID)


def test_it_satisfies_the_protocol(rig: tuple[LambdaWorkerDispatcher, Stubber]) -> None:
    dispatcher: WorkerDispatcher = rig[0]
    assert dispatcher


def test_a_failed_invoke_raises(rig: tuple[LambdaWorkerDispatcher, Stubber]) -> None:
    dispatcher, stub = rig
    stub.add_client_error("invoke", "TooManyRequestsException")
    with pytest.raises(Exception, match="TooManyRequestsException"):
        dispatcher.dispatch(JOB_ID)


def test_an_unexpected_status_raises(rig: tuple[LambdaWorkerDispatcher, Stubber]) -> None:
    dispatcher, stub = rig
    stub.add_response("invoke", {"StatusCode": 200})
    with pytest.raises(RuntimeError, match="202"):
        dispatcher.dispatch(JOB_ID)
