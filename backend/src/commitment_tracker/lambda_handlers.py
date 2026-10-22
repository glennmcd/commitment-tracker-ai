"""Lambda entry points: the API behind API Gateway (Mangum) and the job worker.

One zip serves both functions (docs/decisions/0004-mangum-and-zip.md). On a cold start the
Anthropic key is read from SSM Parameter Store into the settings object, never into the environment
or a log; the table names, bucket and limits come from the function's environment. Nothing runs at
import time, so tests and tooling can import this module freely.
"""

import asyncio
import functools
import logging
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError
from mangum import Mangum
from pydantic import SecretStr

from commitment_tracker.api.app import build_spend_cap, create_app
from commitment_tracker.extractor.factory import build_extractor
from commitment_tracker.guardrails.metrics import enable_emf_output
from commitment_tracker.jobs.audio_store import S3AudioStore
from commitment_tracker.jobs.dispatch import ANALYZE_TEXT
from commitment_tracker.jobs.dynamo import DynamoJobStore
from commitment_tracker.jobs.worker import JobWorker, parse_transcribe_event
from commitment_tracker.settings import Settings
from commitment_tracker.transcription.aws import AwsBatchTranscriber

if TYPE_CHECKING:
    from types_boto3_ssm import SSMClient

logger = logging.getLogger(__name__)

_JOB_ID = re.compile(r"^[0-9a-f]{64}$")


def load_settings(settings: Settings | None = None, *, ssm: "SSMClient | None" = None) -> Settings:
    """The settings with the Anthropic key filled in from SSM when only its parameter is named."""
    loaded = settings or Settings()
    parameter = loaded.anthropic_api_key_parameter
    if loaded.anthropic_api_key is not None or parameter is None:
        return loaded
    client = ssm or boto3.client("ssm")
    try:
        response = client.get_parameter(Name=parameter, WithDecryption=True)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "unknown")
        raise RuntimeError(f"could not read the SSM parameter {parameter} ({code})") from None
    logger.info("api key loaded from ssm")
    return loaded.model_copy(
        update={"anthropic_api_key": SecretStr(response["Parameter"]["Value"])}
    )


# --- API -----------------------------------------------------------------------------------------


def make_api_handler(app: Any) -> Mangum:
    return Mangum(app, lifespan="auto")


@functools.cache
def _api() -> Mangum:
    enable_emf_output()
    return make_api_handler(create_app(settings=load_settings()))


def api_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    response: dict[str, Any] = _api()(event, context)
    return response


# --- Worker --------------------------------------------------------------------------------------


def make_worker_handler(worker: JobWorker) -> Callable[[Any, Any], None]:
    """The worker's handler: a Transcribe event finishes an audio job, a direct invoke runs a text
    job, and anything else is logged and dropped. One runner lives across warm invocations, so the
    model client's connections stay tied to a live event loop."""
    runner = asyncio.Runner()

    def handle(event: Any, context: Any) -> None:
        if not isinstance(event, Mapping):
            logger.info("worker event ignored: not a mapping")
            return
        outcome = parse_transcribe_event(event)
        if outcome is not None:
            runner.run(worker.on_transcribe(outcome))
            return
        job_id = event.get("job_id")
        if (
            event.get("action") == ANALYZE_TEXT
            and isinstance(job_id, str)
            and _JOB_ID.match(job_id)
        ):
            runner.run(worker.on_text_job(job_id))
            return
        logger.info("worker event ignored")

    return handle


def build_worker(settings: Settings) -> JobWorker:
    missing = [
        name
        for name, value in (
            ("JOBS_TABLE", settings.jobs_table),
            ("AUDIO_BUCKET", settings.audio_bucket),
        )
        if value is None
    ]
    if missing or settings.jobs_table is None or settings.audio_bucket is None:
        raise RuntimeError(f"the worker needs {' and '.join(missing)} in its environment")
    s3 = boto3.client("s3")
    return JobWorker(
        DynamoJobStore(boto3.client("dynamodb"), settings.jobs_table),
        S3AudioStore(s3, settings.audio_bucket),
        AwsBatchTranscriber(boto3.client("transcribe"), s3, settings.audio_bucket),
        build_extractor(settings),
        spend=build_spend_cap(settings),
    )


@functools.cache
def _worker_handler() -> Callable[[Any, Any], None]:
    enable_emf_output()
    return make_worker_handler(build_worker(load_settings()))


def worker_handler(event: Any, context: Any) -> None:
    _worker_handler()(event, context)
