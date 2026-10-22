"""FastAPI app: POST /analyze and GET /health.

Handlers are async so the app can run on Lambda behind an ASGI adapter later. Errors use one body,
`{"error": {"code", "message", "details"}}`, with fixed messages: no response or log line carries
transcript text, and validation errors drop the input values FastAPI would otherwise echo.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from commitment_tracker.extractor.errors import (
    ExtractionError,
    ModelOutputInvalid,
    ModelRefused,
    ModelUnavailable,
)
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.factory import build_extractor
from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse
from commitment_tracker.settings import Settings

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model: str
    prompt_version: str


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
    502: {"model": ErrorResponse, "description": "The model failed or its output was invalid"},
}


def _error(
    status: int, code: str, message: str, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status, content=body.model_dump())


def _show_app_logs() -> None:
    """uvicorn configures only its own loggers, so ours need a handler to be seen at INFO."""
    package = logging.getLogger("commitment_tracker")
    if not package.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        package.addHandler(handler)
        package.setLevel(logging.INFO)


def create_app(*, extractor: Extractor | None = None, settings: Settings | None = None) -> FastAPI:
    """With no extractor, the lifespan builds the Anthropic one from settings at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if extractor is None:
            _show_app_logs()
            app.state.extractor = build_extractor(settings or Settings())
        yield

    app = FastAPI(
        title="Commitment Tracker AI",
        version=version("commitment-tracker"),
        description="Extracts commitments from conversation transcripts.",
        lifespan=lifespan,
    )
    if extractor is not None:
        app.state.extractor = extractor

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(loc=list(e["loc"]), msg=e["msg"], type=e["type"]) for e in exc.errors()
        ]
        logger.info("analyze_rejected path=%s errors=%d", request.url.path, len(details))
        return _error(422, "validation_error", "The request is invalid.", details)

    @app.exception_handler(ExtractionError)
    async def _extraction_failed(request: Request, exc: ExtractionError) -> JSONResponse:
        status, code, message = EXTRACTION_ERRORS.get(
            type(exc), (502, "extraction_failed", "The transcript could not be analysed.")
        )
        # Exception text holds field paths, SDK class names and status codes, never transcript text.
        logger.warning("analyze_failed code=%s detail=%s", code, exc)
        return _error(status, code, message)

    @app.get("/health")
    async def health(request: Request) -> HealthResponse:
        active: Extractor = request.app.state.extractor
        return HealthResponse(
            status="ok", model=active.adapter.model, prompt_version=active.prompt.version
        )

    @app.post("/analyze", responses=ERROR_RESPONSES)
    async def analyze(body: AnalyzeRequest, request: Request) -> AnalyzeResponse:
        active: Extractor = request.app.state.extractor
        result = await active.analyze(body)
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

    return app


app = create_app()
