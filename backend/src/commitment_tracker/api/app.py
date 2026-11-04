"""FastAPI app: POST /analyze and GET /health.

Handlers are async so the app can run on Lambda behind an ASGI adapter later. Errors use one body,
`{"error": {"code", "message", "details"}}`, with fixed messages: no response or log line carries
transcript text, and validation errors drop the input values FastAPI would otherwise echo.
"""

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path as plibPath
from typing import Annotated, Any, Literal

import boto3
from fastapi import Depends, FastAPI, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from commitment_tracker.api.errors import (
    AUDIO_INVALID,
    AUDIO_TOO_LONG,
    BATCH_EMPTY,
    BATCH_EXISTS,
    BATCH_VALIDATION,
    BUDGET_EXHAUSTED,
    EXTRACTION_FAILED,
    FORBIDDEN,
    GATEWAY_TIMEOUT,
    IMPORTS_DISABLED,
    INVALID_IMPORT_OPTIONS,
    JOB_NOT_FINISHED,
    JOB_NOT_FOUND,
    JOBS_UNAVAILABLE,
    MODEL_OUTPUT_INVALID,
    MODEL_REFUSED,
    MODEL_UNAVAILABLE,
    RATE_LIMITED,
    SAMPLE_NOT_FOUND,
    SPAN_NOT_FOUND,
    UPLOAD_NOT_FOUND,
    UPLOADS_UNAVAILABLE,
    VALIDATION,
    ApiError,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    route_responses,
)
from commitment_tracker.evaluation.importer import (
    BatchDisabled,
    BatchEmpty,
    BatchExists,
    BatchInvalidImportOptions,
    BatchValidationError,
    ImportReport,
    check_batch,
    import_batch,
)
from commitment_tracker.evaluation.sets import SETS_DIR
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
API_VERSION = "0.5.0"

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
    source: str  # kept as `source` in import.json
    content: str  # the JSONL text
    batch: str
    provenance: str
    generation_prompt: str | None = None  # null = the latest; ignored for hand-written
    today: str


class SampleSummary(BaseModel):
    id: str
    title: str
    duration_ms: int


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


# Each domain error: the registry entry (status, code, fixed message) clients see.
EXTRACTION_ERRORS: dict[type[ExtractionError], ApiError] = {
    ModelUnavailable: MODEL_UNAVAILABLE,
    ModelOutputInvalid: MODEL_OUTPUT_INVALID,
    ModelRefused: MODEL_REFUSED,
}
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
IMPORT_ERRORS: dict[type[Exception], ApiError] = {
    BatchExists: BATCH_EXISTS,
    BatchInvalidImportOptions: INVALID_IMPORT_OPTIONS,
    BatchEmpty: BATCH_EMPTY,
    BatchValidationError: BATCH_VALIDATION,
    BatchDisabled: IMPORTS_DISABLED,
}

# What each route documents: the errors it can raise, plus what API Gateway can answer instead.
ERROR_RESPONSES = route_responses(
    errors=(
        VALIDATION,
        MODEL_REFUSED,
        RATE_LIMITED,
        BUDGET_EXHAUSTED,
        MODEL_UNAVAILABLE,
        MODEL_OUTPUT_INVALID,
        EXTRACTION_FAILED,
    ),
    gateway=(FORBIDDEN, GATEWAY_TIMEOUT),
    limited_success=200,
)
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
SAMPLES_RESPONSES = route_responses(errors=(JOBS_UNAVAILABLE,))
IMPORT_RESPONSES = route_responses(
    errors=(
        IMPORTS_DISABLED,
        BATCH_EXISTS,
        VALIDATION,
        BATCH_VALIDATION,
        INVALID_IMPORT_OPTIONS,
        BATCH_EMPTY,
    )
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
JOB_ID_PATTERN = r"^[0-9a-f]{64}$"


def _error(
    error: ApiError,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
    retry_after: int | None = None,
) -> JSONResponse:
    message = error.text(retry_after if retry_after is not None else "N")
    body = ErrorResponse(error=ErrorBody(code=error.code, message=message, details=details or []))
    return JSONResponse(
        status_code=error.status, content=body.model_dump(mode="json"), headers=headers
    )


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
    sets_dir: plibPath | None = None,
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
        return _error(VALIDATION, details)

    @app.exception_handler(RateLimited)
    async def _rate_limited(request: Request, exc: RateLimited) -> JSONResponse:
        logger.info("rate_limited path=%s", request.url.path)
        return _error(
            RATE_LIMITED,
            headers={"Retry-After": str(exc.retry_after)},
            retry_after=exc.retry_after,
        )

    @app.exception_handler(DailyBudgetExhausted)
    async def _budget_exhausted(request: Request, exc: DailyBudgetExhausted) -> JSONResponse:
        logger.info("daily_budget_exhausted path=%s", request.url.path)
        return _error(BUDGET_EXHAUSTED, headers={"Retry-After": str(exc.retry_after)})

    @app.exception_handler(ExtractionError)
    async def _extraction_failed(request: Request, exc: ExtractionError) -> JSONResponse:
        error = EXTRACTION_ERRORS.get(type(exc), EXTRACTION_FAILED)
        # Exception text holds field paths, SDK class names and status codes, never transcript text.
        logger.warning("analyze_failed code=%s detail=%s", error.code, exc)
        return _error(error)

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
        error = next(JOB_ERRORS[cls] for cls in type(exc).__mro__ if cls in JOB_ERRORS)
        logger.info("job_rejected path=%s code=%s", request.url.path, error.code)
        return _error(error)

    @app.exception_handler(BatchDisabled)
    @app.exception_handler(BatchExists)
    @app.exception_handler(BatchInvalidImportOptions)
    @app.exception_handler(BatchEmpty)
    @app.exception_handler(BatchValidationError)
    async def _batch_invalid(request: Request, exc: Exception) -> JSONResponse:
        error = next(IMPORT_ERRORS[cls] for cls in type(exc).__mro__ if cls in IMPORT_ERRORS)
        logger.info("import_error path=%s code=%s", request.url.path, error.code)
        return _error(error)

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
            return _error(UPLOADS_UNAVAILABLE)
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

    @app.get(
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
            return _error(JOB_NOT_FOUND)
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

    @app.get("/samples", responses=SAMPLES_RESPONSES)
    async def list_samples(request: Request) -> list[SampleSummary]:
        clips = _jobs(request).samples().all()
        return [SampleSummary(id=c.id, title=c.title, duration_ms=c.duration_ms) for c in clips]

    @app.post("/eval-imports/check", response_model=ImportReport, responses=IMPORT_RESPONSES)
    async def check_import(body: ImportRequest, request: Request) -> ImportReport | JSONResponse:
        sets_dir: str | None = getattr(request.app.state, "sets_dir", None)
        if sets_dir is None:
            # return _error(404, "imports_disabled", "Imports are disabled")
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

    @app.post(
        "/eval-imports", status_code=201, response_model=ImportReport, responses=IMPORT_RESPONSES
    )
    async def create_import(body: ImportRequest, request: Request) -> ImportReport | JSONResponse:
        sets_dir: str | None = getattr(request.app.state, "sets_dir", None)
        if sets_dir is None:
            # return _error(404, "imports_disabled", "Imports are disabled")
            raise BatchDisabled()

        _, report = import_batch(
            plibPath(body.source),
            batch=body.batch,
            provenance=body.provenance,
            generation_prompt=body.generation_prompt,
            root=plibPath(sets_dir),
            today=date.fromisoformat(body.today),
        )
        if report.imported == 0:
            raise BatchEmpty()
        return report

    return app


app = create_app()
