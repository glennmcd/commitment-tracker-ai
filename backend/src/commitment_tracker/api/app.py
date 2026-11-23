"""FastAPI app: POST /analyze, GET /health and the eval-import routes; the job routes live in
`job_routes`.

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
from typing import Any, Literal

import boto3
from fastapi import Depends, FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from commitment_tracker.api import job_routes
from commitment_tracker.api.errors import (
    BATCH_EMPTY,
    BATCH_EXISTS,
    BATCH_VALIDATION,
    BUDGET_EXHAUSTED,
    EXTRACTION_FAILED,
    FORBIDDEN,
    GATEWAY_TIMEOUT,
    IMPORTS_DISABLED,
    INVALID_IMPORT_OPTIONS,
    MODEL_OUTPUT_INVALID,
    MODEL_REFUSED,
    MODEL_UNAVAILABLE,
    RATE_LIMITED,
    VALIDATION,
    ApiError,
    ErrorDetail,
    route_responses,
)
from commitment_tracker.api.guards import (
    RateLimited,
    error_response,
    limited,
    within_budget,
)
from commitment_tracker.api.job_routes import JOB_ERRORS
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
from commitment_tracker.feedback.service import (
    FeedbackJobNotFound,
    FeedbackService,
    FeedbackSpanNotFound,
    JobNotFinished,
)
from commitment_tracker.guardrails.metrics import emit_spend_fraction
from commitment_tracker.guardrails.ratelimit import DynamoRateLimitStore, RateLimiter
from commitment_tracker.guardrails.spend import DailyBudgetExhausted, DynamoSpendStore, SpendCap
from commitment_tracker.jobs.audio import AudioInvalid, AudioTooLong
from commitment_tracker.jobs.service import (
    JobService,
    JobsUnavailable,
    SampleNotFound,
    UploadNotFound,
)
from commitment_tracker.jobs.uploads import UploadSigner
from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse
from commitment_tracker.settings import Settings

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


class ImportRequest(BaseModel):
    source: str  # kept as `source` in import.json
    content: str  # the JSONL text
    batch: str
    provenance: str
    generation_prompt: str | None = None  # null = the latest; ignored for hand-written
    today: str


# Each domain error: the registry entry (status, code, fixed message) clients see.
EXTRACTION_ERRORS: dict[type[ExtractionError], ApiError] = {
    ModelUnavailable: MODEL_UNAVAILABLE,
    ModelOutputInvalid: MODEL_OUTPUT_INVALID,
    ModelRefused: MODEL_REFUSED,
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


def _show_app_logs() -> None:
    """uvicorn configures only its own loggers, so ours need a handler to be seen at INFO."""
    package = logging.getLogger("commitment_tracker")
    if not package.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        package.addHandler(handler)
        package.setLevel(logging.INFO)


def build_spend_cap(settings: Settings) -> SpendCap | None:
    if settings.guardrails_table is None:
        return None
    store = DynamoSpendStore(boto3.client("dynamodb"), settings.guardrails_table)
    return SpendCap(store, settings.daily_budget_usd, on_total=emit_spend_fraction)


def build_limiter(settings: Settings) -> RateLimiter | None:
    if settings.guardrails_table is None:
        return None
    return RateLimiter(DynamoRateLimitStore(boto3.client("dynamodb"), settings.guardrails_table))


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
            app.state.uploads = uploads or job_routes.build_upload_signer(active_settings)
            spend_cap = spend or build_spend_cap(active_settings)
            app.state.jobs = jobs or job_routes.build_job_service(active_settings, spend_cap)
            app.state.limiter = limiter or build_limiter(active_settings)
            app.state.spend = spend_cap
            app.state.feedback = feedback or job_routes.build_feedback_service(active_settings)
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
        return error_response(VALIDATION, details)

    @app.exception_handler(RateLimited)
    async def _rate_limited(request: Request, exc: RateLimited) -> JSONResponse:
        logger.info("rate_limited path=%s", request.url.path)
        return error_response(
            RATE_LIMITED,
            headers={"Retry-After": str(exc.retry_after)},
            retry_after=exc.retry_after,
        )

    @app.exception_handler(DailyBudgetExhausted)
    async def _budget_exhausted(request: Request, exc: DailyBudgetExhausted) -> JSONResponse:
        logger.info("daily_budget_exhausted path=%s", request.url.path)
        return error_response(BUDGET_EXHAUSTED, headers={"Retry-After": str(exc.retry_after)})

    @app.exception_handler(ExtractionError)
    async def _extraction_failed(request: Request, exc: ExtractionError) -> JSONResponse:
        error = EXTRACTION_ERRORS.get(type(exc), EXTRACTION_FAILED)
        # Exception text holds field paths, SDK class names and status codes, never transcript text.
        logger.warning("analyze_failed code=%s detail=%s", error.code, exc)
        return error_response(error)

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
        return error_response(error)

    @app.exception_handler(BatchDisabled)
    @app.exception_handler(BatchExists)
    @app.exception_handler(BatchInvalidImportOptions)
    @app.exception_handler(BatchEmpty)
    @app.exception_handler(BatchValidationError)
    async def _batch_invalid(request: Request, exc: Exception) -> JSONResponse:
        error = next(IMPORT_ERRORS[cls] for cls in type(exc).__mro__ if cls in IMPORT_ERRORS)
        logger.info("import_error path=%s code=%s", request.url.path, error.code)
        return error_response(error)

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

    app.include_router(job_routes.router)

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
