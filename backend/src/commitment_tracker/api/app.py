"""FastAPI app: POST /analyze and GET /health.

Handlers are async so the app can run on Lambda behind an ASGI adapter later. Errors use one body,
`{"error": {"code", "message", "details"}}`, with fixed messages: no response or log line carries
transcript text, and validation errors drop the input values FastAPI would otherwise echo.
"""

from datetime import date
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
from pathlib import Path as plibPath

import boto3
from commitment_tracker.evaluation.sets import SETS_DIR
from fastapi import Depends, FastAPI, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from commitment_tracker.evaluation.importer import (ImportReport,
                                                    check_batch, 
                                                    import_batch, 
                                                    BatchError, 
                                                    BatchExists,
                                                    BatchDisabled,
                                                    BatchInvalidImportOptions,
                                                    BatchEmpty,
                                                    BatchValidationError)
from commitment_tracker.extractor.errors import (
    ExtractionError,
    ModelOutputInvalid,
    ModelRefused,
    ModelUnavailable,
)
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.factory import build_extractor
from commitment_tracker.feedback.dynamo import DynamoFeedbackStore
from commitment_tracker.feedback.service import (
    FeedbackJobNotFound,
    FeedbackService,
    FeedbackSpanNotFound,
    JobNotFinished,
)
from commitment_tracker.guardrails.metrics import emit_spend_fraction
from commitment_tracker.guardrails.ratelimit import (
    DynamoRateLimitStore,
    RateLimiter,
    client_ip,
)
from commitment_tracker.guardrails.spend import DailyBudgetExhausted, DynamoSpendStore, SpendCap
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
    AnalyzeRequest,
    AnalyzeResponse,
    FeedbackRequest,
    FeedbackResponse,
    JobRequest,
    Turn,
    UploadResponse,
)
from commitment_tracker.settings import Settings
from commitment_tracker.transcription.aws import AwsBatchTranscriber

logger = logging.getLogger(__name__)

# The API contract version, published as info.version in openapi.json. Bump it by hand when the
# request or response shape changes; it is separate from the release version (commitment_tracker
# .__version__), so releases don't change openapi.json or the frontend client generated from it.
API_VERSION = "0.3.0"

# A link label such as "alice" or "mailing-2026-10": short and plain, so it cannot forge a log line.
SOURCE_LABEL = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _publish_site_password_scheme(app: FastAPI) -> None:
    """Document the site password in the OpenAPI schema.

    API Gateway's Lambda authorizer checks the Authorization header before a request reaches
    this app (infra/lib/api-stack.ts), so the app never reads it. The scheme only tells clients
    to send it. Every endpoint needs it except the health check.
    """
    build = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = build()
            schema.setdefault("components", {}).setdefault("securitySchemes", {})[
                "SitePassword"
            ] = {
                "type": "apiKey",
                "in": "header",
                "name": "Authorization",
                "description": "The site password, sent as the whole Authorization header value.",
            }
            schema["security"] = [{"SitePassword": []}]
            schema["paths"]["/health"]["get"]["security"] = []
        return app.openapi_schema or {}

    app.openapi = openapi  # type: ignore[method-assign]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model: str
    prompt_version: str


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    transcript: list[Turn] | None = None
    analysis: AnalyzeResponse | None = None
    error_code: str | None = None
    latency_ms: Latency

class ImportRequest(BaseModel): 
    source:str # kept as `source` in import.json
    content:str # the JSONL text
    batch:str
    provenance:str
    generation_prompt: str | None = None   # null = the latest; ignored for hand-written
    today: str

class SampleSummary(BaseModel):
    id: str
    title: str
    duration_ms: int


class ErrorDetail(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


RATE_LIMITED: dict[str, object] = {
    "model": ErrorResponse,
    "description": "Too many requests from this client; see Retry-After",
}


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


BUDGET_EXHAUSTED: dict[str, object] = {
    "model": ErrorResponse,
    "description": "The day's spending cap is reached; see Retry-After (seconds to UTC midnight)",
}


# Each extraction failure: HTTP status, error code and the fixed message clients see.
EXTRACTION_ERRORS: dict[type[ExtractionError], tuple[int, str, str]] = {
    ModelUnavailable: (502, "model_unavailable", "The model is unavailable. Try again later."),
    ModelOutputInvalid: (
        502,
        "model_output_invalid",
        "The model's output failed validation twice. Try again.",
    ),
    ModelRefused: (422, "model_refused", "The model declined to analyse this transcript."),
}
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    422: {"model": ErrorResponse, "description": "Invalid request, or the model refused it"},
    429: RATE_LIMITED,
    503: BUDGET_EXHAUSTED,
    502: {"model": ErrorResponse, "description": "The model failed or its output was invalid"},
}
UPLOAD_RESPONSES: dict[int | str, dict[str, object]] = {
    429: RATE_LIMITED,
    503: {"model": ErrorResponse, "description": "Audio storage is not configured"},
}
JOB_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "The upload, sample or job does not exist"},
    429: RATE_LIMITED,
    422: {"model": ErrorResponse, "description": "Invalid request, or the audio is not accepted"},
    503: {
        "model": ErrorResponse,
        "description": "Jobs are not configured, or the day's spending cap is reached",
    },
}
# Domain errors raised by the job service: HTTP status, error code and the fixed message.
JOB_ERRORS: dict[type[Exception], tuple[int, str, str]] = {
    UploadNotFound: (404, "upload_not_found", "No upload with that id. It may have expired."),
    SampleNotFound: (404, "sample_not_found", "No sample clip with that id."),
    AudioTooLong: (422, "audio_too_long", "The recording is longer than 60 seconds."),
    AudioInvalid: (422, "audio_invalid", "The audio is not a 16 kHz mono 16-bit WAV."),
    JobsUnavailable: (503, "jobs_unavailable", "Jobs are not available."),
    FeedbackJobNotFound: (404, "job_not_found", "No job with that id. It may have expired."),
    JobNotFinished: (409, "job_not_finished", "The job has no results to give feedback on."),
    FeedbackSpanNotFound: (404, "span_not_found", "The job has no span with that index."),
}
IMPORT_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "Imports are disabled"},
    409: {"model": ErrorResponse, "description": "The batch already exists"},
    422: {"model": ErrorResponse, "description": "Invalid request, or the import was refused"},
}
IMPORT_ERRORS: dict[type[Exception], tuple[int, str, str]] = {
    BatchExists: (409, "batch_exists", "The batch already exists"),
    BatchInvalidImportOptions: (422, "invalid_import_options", "The batch name or provenance breaks a rule"),
    BatchEmpty: (422, "batch_empty", "The batch is empty"),
    BatchValidationError: (422, "validation_error", "A field is missing or the content is over the size cap"),
    BatchDisabled: (404, "imports_disabled", "Imports are disabled"),
    # NothingToImport: (422, "nothing_to_import", "Invalid request, or the import was refused"),
}
FEEDBACK_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "The job or the span does not exist"},
    409: {"model": ErrorResponse, "description": "The job is not finished"},
    429: RATE_LIMITED,
    503: {"model": ErrorResponse, "description": "Feedback storage is not configured"},
}
JOB_ID_PATTERN = r"^[0-9a-f]{64}$"


def _error(
    status: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)


async def within_budget(request: Request) -> None:
    """Refuse new work once the day's spending cap is reached. Runs before the body is read."""
    spend: SpendCap | None = request.app.state.spend
    if spend is not None:
        await run_in_threadpool(spend.check)


def limited(rule: str) -> Any:
    """A dependency that counts the request under `rule` and refuses it past the limit. It runs
    before the body is validated, so malformed requests use up the budget too."""

    async def check(request: Request, response: Response) -> None:
        limiter: RateLimiter | None = request.app.state.limiter
        if limiter is None:
            return
        decision = await run_in_threadpool(limiter.check, rule, client_ip(request))
        response.headers["ratelimit-limit"] = str(decision.limit)
        response.headers["ratelimit-remaining"] = str(decision.remaining)
        response.headers["ratelimit-reset"] = str(decision.retry_after)
        if not decision.allowed:
            raise RateLimited(decision.retry_after)

    return Depends(check)


def _show_app_logs() -> None:
    """uvicorn configures only its own loggers, so ours need a handler to be seen at INFO."""
    package = logging.getLogger("commitment_tracker")
    if not package.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        package.addHandler(handler)
        package.setLevel(logging.INFO)


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


def build_spend_cap(settings: Settings) -> SpendCap | None:
    if settings.guardrails_table is None:
        return None
    store = DynamoSpendStore(boto3.client("dynamodb"), settings.guardrails_table)
    return SpendCap(store, settings.daily_budget_usd, on_total=emit_spend_fraction)


def build_feedback_service(settings: Settings) -> FeedbackService | None:
    if settings.jobs_table is None or settings.feedback_table is None:
        return None
    dynamodb = boto3.client("dynamodb")
    return FeedbackService(
        DynamoJobStore(dynamodb, settings.jobs_table),
        DynamoFeedbackStore(dynamodb, settings.feedback_table),
    )


def build_limiter(settings: Settings) -> RateLimiter | None:
    if settings.guardrails_table is None:
        return None
    return RateLimiter(DynamoRateLimitStore(boto3.client("dynamodb"), settings.guardrails_table))


def _job_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        status=job.status,
        transcript=job.turns,
        analysis=job.analysis,
        error_code=job.error_code,
        latency_ms=job.latency(),
    )


def create_app(
    *,
    extractor: Extractor | None = None,
    settings: Settings | None = None,
    uploads: UploadSigner | None = None,
    jobs: JobService | None = None,
    limiter: RateLimiter | None = None,
    spend: SpendCap | None = None,
    feedback: FeedbackService | None = None,
    sets_dir: plibPath | None = None
) -> FastAPI:
    """With no extractor, the lifespan builds the Anthropic one, and the upload signer when an
    audio bucket is configured, from settings at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if extractor is None:
            _show_app_logs()
            active_settings = settings or Settings()
            app.state.extractor = build_extractor(active_settings)
            app.state.uploads = uploads or build_upload_signer(active_settings)
            spend_cap = spend or build_spend_cap(active_settings)
            app.state.jobs = jobs or build_job_service(active_settings, spend_cap)
            app.state.limiter = limiter or build_limiter(active_settings)
            app.state.spend = spend_cap
            app.state.feedback = feedback or build_feedback_service(active_settings)
            app.state.sets_dir = SETS_DIR if active_settings.eval_imports_enabled else None
        yield

    app = FastAPI(
        title="Commitment Tracker AI",
        version=API_VERSION,
        description="Extracts commitments from conversation transcripts.",
        lifespan=lifespan,
    )
    _publish_site_password_scheme(app)
    app.state.uploads = uploads
    app.state.jobs = jobs
    app.state.limiter = limiter
    app.state.spend = spend
    app.state.feedback = feedback
    if extractor is not None:
        app.state.extractor = extractor
        
    if settings and settings.eval_imports_enabled:
        app.state.sets_dir = sets_dir if sets_dir is not None else SETS_DIR
    else:
        app.state.sets_dir = None
        
    @app.middleware("http")
    async def _log_source(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Who followed which link: the page sends the label from the link's `?pwsource=`. Only that
        # label is logged, never the Authorization header or anything else.
        raw = request.headers.get("x-source")
        if raw is not None:
            source = raw if SOURCE_LABEL.fullmatch(raw) else "invalid"
            logger.info(
                "request method=%s path=%s pwsource=%s", request.method, request.url.path, source
            )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(loc=list(e["loc"]), msg=e["msg"], type=e["type"]) for e in exc.errors()
        ]
        logger.info("analyze_rejected path=%s errors=%d", request.url.path, len(details))
        return _error(422, "validation_error", "The request is invalid.", details)

    @app.exception_handler(RateLimited)
    async def _rate_limited(request: Request, exc: RateLimited) -> JSONResponse:
        logger.info("rate_limited path=%s", request.url.path)
        return _error(
            429,
            "rate_limited",
            f"Too many requests. Try again in {exc.retry_after} seconds.",
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(DailyBudgetExhausted)
    async def _budget_exhausted(request: Request, exc: DailyBudgetExhausted) -> JSONResponse:
        logger.info("daily_budget_exhausted path=%s", request.url.path)
        return _error(
            503,
            "daily_budget_exhausted",
            "The demo has reached its daily spending limit. Try again after midnight UTC.",
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(ExtractionError)
    async def _extraction_failed(request: Request, exc: ExtractionError) -> JSONResponse:
        status, code, message = EXTRACTION_ERRORS.get(
            type(exc), (502, "extraction_failed", "The transcript could not be analysed.")
        )
        # Exception text holds field paths, SDK class names and status codes, never transcript text.
        logger.warning("analyze_failed code=%s detail=%s", code, exc)
        return _error(status, code, message)

    @app.exception_handler(UploadNotFound)
    @app.exception_handler(SampleNotFound)
    @app.exception_handler(AudioTooLong)
    @app.exception_handler(AudioInvalid)
    @app.exception_handler(JobsUnavailable)
    @app.exception_handler(FeedbackJobNotFound)
    @app.exception_handler(JobNotFinished)
    @app.exception_handler(FeedbackSpanNotFound)
    async def _job_failed(request: Request, exc: Exception) -> JSONResponse:
        # Walk the MRO so TextJobsUnavailable finds JobsUnavailable's entry.
        status, code, message = next(
            JOB_ERRORS[cls] for cls in type(exc).__mro__ if cls in JOB_ERRORS
        )
        logger.info("job_rejected path=%s code=%s", request.url.path, code)
        return _error(status, code, message)

    @app.exception_handler(BatchDisabled)
    @app.exception_handler(BatchExists)
    @app.exception_handler(BatchInvalidImportOptions)
    @app.exception_handler(BatchEmpty)
    @app.exception_handler(BatchValidationError)
    async def _batch_invalid(request: Request, exc: Exception) -> JSONResponse:
        status, code, message = next(
                    IMPORT_ERRORS[cls] for cls in type(exc).__mro__ if cls in IMPORT_ERRORS
                )
        logger.info("import_error path=%s code=%s", request.url.path, code)
        return _error(status, code, message)

    # @app.exception_handler(BatchEmpty)
    # async def _batch_empty(request: Request, exc: BatchEmpty) -> JSONResponse:
    #     status, code, message = IMPORT_ERRORS.get(
    #         type(exc), (422, "batch_empty", "The batch is empty")
    #     )
    #     logger.info("batch_empty path=%s code=%s", request.url.path, code)
    #     return _error(status, code, message)

    @app.get("/health")
    async def health(request: Request) -> HealthResponse:
        active: Extractor = request.app.state.extractor
        return HealthResponse(
            status="ok", model=active.adapter.model, prompt_version=active.prompt.version
        )

    @app.post(
        "/analyze",
        responses=ERROR_RESPONSES,
        dependencies=[limited("analyze"), Depends(within_budget)],
    )
    async def analyze(body: AnalyzeRequest, request: Request) -> AnalyzeResponse:
        active: Extractor = request.app.state.extractor
        result = await active.analyze(body)
        spend: SpendCap | None = request.app.state.spend
        if spend is not None and result.metadata.cost_usd is not None:
            await run_in_threadpool(spend.record, result.metadata.cost_usd)
        meta = result.metadata
        logger.info(
            "analyze turns=%d spans=%d dropped_quotes=%d attempts=%d latency_ms=%d served_by=%s",
            len(body.transcript),
            len(result.spans),
            meta.dropped_quotes,
            meta.attempts,
            meta.latency_ms,
            meta.served_by,
        )
        return result

    @app.post(
        "/uploads",
        response_model=UploadResponse,
        responses=UPLOAD_RESPONSES,
        dependencies=[limited("uploads")],
    )
    async def create_upload(request: Request) -> UploadResponse | JSONResponse:
        signer: UploadSigner | None = request.app.state.uploads
        if signer is None:
            return _error(503, "uploads_unavailable", "Audio uploads are not available.")
        ticket = signer.presign()
        return UploadResponse(
            upload_id=ticket.upload_id,
            url=ticket.url,
            fields=ticket.fields,
            max_bytes=MAX_AUDIO_BYTES,
            expires_in=ticket.expires_in,
        )

    def _jobs(request: Request) -> JobService:
        service: JobService | None = request.app.state.jobs
        if service is None:
            raise JobsUnavailable("jobs are not configured")
        return service

    @app.post(
        "/jobs",
        status_code=202,
        response_model=JobResponse,
        responses=JOB_RESPONSES,
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

    @app.get(
        "/jobs/{job_id}",
        response_model=JobResponse,
        responses=JOB_RESPONSES,
        dependencies=[limited("job_status")],
    )
    async def get_job(
        request: Request, job_id: Annotated[str, Path(pattern=JOB_ID_PATTERN)]
    ) -> JobResponse | JSONResponse:
        job = await run_in_threadpool(_jobs(request).get, job_id)
        if job is None:
            return _error(404, "job_not_found", "No job with that id. It may have expired.")
        return _job_response(job)

    @app.post(
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

    @app.get("/samples", responses=JOB_RESPONSES)
    async def list_samples(request: Request) -> list[SampleSummary]:
        clips = _jobs(request).samples().all()
        return [SampleSummary(id=c.id, title=c.title, duration_ms=c.duration_ms) for c in clips]

    @app.post(
        "/eval-imports/check",
        response_model=ImportReport,
        responses=IMPORT_RESPONSES)
    async def check_import(body: ImportRequest, request: Request) -> ImportReport | JSONResponse:
        sets_dir: str | None = getattr(request.app.state, "sets_dir", None)
        if sets_dir is None:
            #return _error(404, "imports_disabled", "Imports are disabled")
            raise BatchDisabled()
       
        report, _ = check_batch(
            body.content.splitlines(),
            body.source,
            batch=body.batch,
            provenance=body.provenance,
            generation_prompt=body.generation_prompt,
            root=plibPath(sets_dir),
            today=date.fromisoformat(body.today),
        )
        return report
       
                
    @app.post("/eval-imports",
              status_code=201,
              response_model=ImportReport,
              responses=IMPORT_RESPONSES)
    async def create_import(body: ImportRequest, request: Request) -> ImportReport | JSONResponse:
        sets_dir: str | None = getattr(request.app.state, "sets_dir", None)
        if sets_dir is None:
            #return _error(404, "imports_disabled", "Imports are disabled")
            raise BatchDisabled()
               
        _, report = import_batch(
            plibPath(body.source),
            batch=body.batch,
            provenance=body.provenance,
            generation_prompt=body.generation_prompt,
            root=plibPath(sets_dir),
            today=date.fromisoformat(body.today),
        )
        return report

    return app


app = create_app()
