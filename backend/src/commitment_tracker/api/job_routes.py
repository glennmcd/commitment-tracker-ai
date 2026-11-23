"""The routes that upload audio, start and read jobs, take feedback on a job, and list the samples.

They live on their own router, which `create_app` includes. Their error mapping (`JOB_ERRORS`) is
registered on the app, as is every exception handler, because FastAPI routers can't carry them.
"""

from typing import Annotated

import boto3
from fastapi import APIRouter, Depends, Path, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from commitment_tracker.api.errors import (
    AUDIO_INVALID,
    AUDIO_TOO_LONG,
    BUDGET_EXHAUSTED,
    FORBIDDEN,
    GATEWAY_TIMEOUT,
    JOB_NOT_FINISHED,
    JOB_NOT_FOUND,
    JOBS_UNAVAILABLE,
    RATE_LIMITED,
    SAMPLE_NOT_FOUND,
    SPAN_NOT_FOUND,
    UPLOAD_NOT_FOUND,
    UPLOADS_UNAVAILABLE,
    VALIDATION,
    ApiError,
    route_responses,
)
from commitment_tracker.api.guards import error_response, limited, within_budget
from commitment_tracker.feedback.dynamo import DynamoFeedbackStore
from commitment_tracker.feedback.service import (
    FeedbackJobNotFound,
    FeedbackService,
    FeedbackSpanNotFound,
    JobNotFinished,
)
from commitment_tracker.guardrails.spend import SpendCap
from commitment_tracker.jobs.audio import MAX_AUDIO_BYTES, AudioInvalid, AudioTooLong
from commitment_tracker.jobs.audio_store import S3AudioStore
from commitment_tracker.jobs.dispatch import LambdaWorkerDispatcher
from commitment_tracker.jobs.dynamo import DynamoJobStore
from commitment_tracker.jobs.record import JobRecord, JobStatus, Latency
from commitment_tracker.jobs.samples import load_catalog
from commitment_tracker.jobs.service import (
    JobService,
    JobsUnavailable,
    SampleNotFound,
    UploadNotFound,
)
from commitment_tracker.jobs.uploads import S3UploadSigner, UploadSigner
from commitment_tracker.schemas import (
    AnalyzeResponse,
    FeedbackRequest,
    FeedbackResponse,
    JobRequest,
    Turn,
    UploadResponse,
)
from commitment_tracker.settings import Settings
from commitment_tracker.transcription.aws import AwsBatchTranscriber

router = APIRouter()


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    transcript: list[Turn] | None = None
    analysis: AnalyzeResponse | None = None
    error_code: str | None = None
    latency_ms: Latency


class SampleSummary(BaseModel):
    id: str
    title: str
    duration_ms: int


# Each domain error: the registry entry (status, code, fixed message) clients see.
JOB_ERRORS: dict[type[Exception], ApiError] = {
    UploadNotFound: UPLOAD_NOT_FOUND,
    SampleNotFound: SAMPLE_NOT_FOUND,
    AudioTooLong: AUDIO_TOO_LONG,
    AudioInvalid: AUDIO_INVALID,
    JobsUnavailable: JOBS_UNAVAILABLE,
    FeedbackJobNotFound: JOB_NOT_FOUND,
    JobNotFinished: JOB_NOT_FINISHED,
    FeedbackSpanNotFound: SPAN_NOT_FOUND,
}

UPLOAD_RESPONSES = route_responses(errors=(RATE_LIMITED, UPLOADS_UNAVAILABLE), limited_success=200)
CREATE_JOB_RESPONSES = route_responses(
    errors=(
        UPLOAD_NOT_FOUND,
        SAMPLE_NOT_FOUND,
        VALIDATION,
        AUDIO_TOO_LONG,
        AUDIO_INVALID,
        RATE_LIMITED,
        JOBS_UNAVAILABLE,
        BUDGET_EXHAUSTED,
    ),
    gateway=(FORBIDDEN, GATEWAY_TIMEOUT),
    limited_success=202,
)
GET_JOB_RESPONSES = route_responses(
    errors=(VALIDATION, JOB_NOT_FOUND, RATE_LIMITED, JOBS_UNAVAILABLE), limited_success=200
)
FEEDBACK_RESPONSES = route_responses(
    errors=(
        VALIDATION,
        JOB_NOT_FOUND,
        SPAN_NOT_FOUND,
        JOB_NOT_FINISHED,
        RATE_LIMITED,
        JOBS_UNAVAILABLE,
    ),
    limited_success=200,
)
SAMPLES_RESPONSES = route_responses(errors=(JOBS_UNAVAILABLE,))
JOB_ID_PATTERN = r"^[0-9a-f]{64}$"


def build_upload_signer(settings: Settings) -> UploadSigner | None:
    if settings.audio_bucket is None:
        return None
    s3 = boto3.client("s3")
    return S3UploadSigner(s3, settings.audio_bucket, expires_in=settings.upload_url_ttl_seconds)


def build_job_service(settings: Settings, spend: SpendCap | None = None) -> JobService | None:
    """Wired to AWS when the bucket and table are configured. Text jobs need the worker's function
    name too; without it they answer 503."""
    if settings.audio_bucket is None or settings.jobs_table is None:
        return None
    s3 = boto3.client("s3")
    dispatcher = (
        None
        if settings.worker_function_name is None
        else LambdaWorkerDispatcher(boto3.client("lambda"), settings.worker_function_name)
    )
    return JobService(
        DynamoJobStore(boto3.client("dynamodb"), settings.jobs_table),
        S3AudioStore(s3, settings.audio_bucket),
        AwsBatchTranscriber(boto3.client("transcribe"), s3, settings.audio_bucket),
        load_catalog(),
        dispatcher,
        spend=spend,
    )


def build_feedback_service(settings: Settings) -> FeedbackService | None:
    if settings.jobs_table is None or settings.feedback_table is None:
        return None
    dynamodb = boto3.client("dynamodb")
    return FeedbackService(
        DynamoJobStore(dynamodb, settings.jobs_table),
        DynamoFeedbackStore(dynamodb, settings.feedback_table),
    )


def _job_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        status=job.status,
        transcript=job.turns,
        analysis=job.analysis,
        error_code=job.error_code,
        latency_ms=job.latency(),
    )


def _jobs(request: Request) -> JobService:
    service: JobService | None = request.app.state.jobs
    if service is None:
        raise JobsUnavailable("jobs are not configured")
    return service


@router.post(
    "/uploads",
    response_model=UploadResponse,
    responses=UPLOAD_RESPONSES,
    dependencies=[limited("uploads")],
)
async def create_upload(request: Request) -> UploadResponse | JSONResponse:
    signer: UploadSigner | None = request.app.state.uploads
    if signer is None:
        return error_response(UPLOADS_UNAVAILABLE)
    ticket = signer.presign()
    return UploadResponse(
        upload_id=ticket.upload_id,
        url=ticket.url,
        fields=ticket.fields,
        max_bytes=MAX_AUDIO_BYTES,
        expires_in=ticket.expires_in,
    )


@router.post(
    "/jobs",
    status_code=202,
    response_model=JobResponse,
    responses=CREATE_JOB_RESPONSES,
    dependencies=[limited("jobs"), Depends(within_budget)],
)
async def create_job(body: JobRequest, request: Request) -> JobResponse:
    service = _jobs(request)
    if body.upload_id is not None:
        job = await run_in_threadpool(
            service.start_upload, body.upload_id, body.call_date, body.speaker_names
        )
    elif body.sample_id is not None:
        job = await run_in_threadpool(
            service.start_sample, body.sample_id, body.call_date, body.speaker_names
        )
    else:
        assert body.transcript is not None  # JobRequest allows exactly one source
        job = await run_in_threadpool(service.start_text, body.transcript, body.call_date)
    return _job_response(job)


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    responses=GET_JOB_RESPONSES,
    dependencies=[limited("job_status")],
)
async def get_job(
    request: Request, job_id: Annotated[str, Path(pattern=JOB_ID_PATTERN)]
) -> JobResponse | JSONResponse:
    job = await run_in_threadpool(_jobs(request).get, job_id)
    if job is None:
        return error_response(JOB_NOT_FOUND)
    return _job_response(job)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses=FEEDBACK_RESPONSES,
    dependencies=[limited("feedback")],
)
async def create_feedback(body: FeedbackRequest, request: Request) -> FeedbackResponse:
    service: FeedbackService | None = request.app.state.feedback
    if service is None:
        raise JobsUnavailable("feedback is not configured")
    result = await run_in_threadpool(service.submit, body)
    return FeedbackResponse(transcript_kept=result.transcript_kept)


@router.get("/samples", responses=SAMPLES_RESPONSES)
async def list_samples(request: Request) -> list[SampleSummary]:
    clips = _jobs(request).samples().all()
    return [SampleSummary(id=c.id, title=c.title, duration_ms=c.duration_ms) for c in clips]
