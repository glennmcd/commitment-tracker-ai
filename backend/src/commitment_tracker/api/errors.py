"""Every error the API answers with: status, code and the fixed message clients see.

One registry feeds both the handlers in `app.py` and the OpenAPI schema, so the published list of
errors cannot drift from what the app sends. Two kinds of error exist:

- App errors use the `ErrorResponse` body, `{"error": {"code", "message", "details"}}`.
- Gateway errors (403 from the password authorizer, 504 on timeout) are sent by API Gateway before
  or instead of the app, with a bare `{"message": ...}` body. The app never produces them.

Messages carry no transcript text. A message may hold `{retry_after}`, filled in when it is sent.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    RATE_LIMITED = "rate_limited"
    DAILY_BUDGET_EXHAUSTED = "daily_budget_exhausted"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    MODEL_REFUSED = "model_refused"
    EXTRACTION_FAILED = "extraction_failed"
    UPLOADS_UNAVAILABLE = "uploads_unavailable"
    UPLOAD_NOT_FOUND = "upload_not_found"
    SAMPLE_NOT_FOUND = "sample_not_found"
    AUDIO_TOO_LONG = "audio_too_long"
    AUDIO_INVALID = "audio_invalid"
    JOBS_UNAVAILABLE = "jobs_unavailable"
    JOB_NOT_FOUND = "job_not_found"
    JOB_NOT_FINISHED = "job_not_finished"
    SPAN_NOT_FOUND = "span_not_found"
    IMPORTS_DISABLED = "imports_disabled"
    BATCH_EXISTS = "batch_exists"
    INVALID_IMPORT_OPTIONS = "invalid_import_options"
    BATCH_EMPTY = "batch_empty"


class ErrorDetail(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


class GatewayErrorResponse(BaseModel):
    """What API Gateway sends when it answers instead of the app."""

    message: str


@dataclass(frozen=True)
class ApiError:
    status: int
    code: ErrorCode
    message: str
    retry_after: bool = False  # sent with a Retry-After header (seconds)
    example_details: tuple[ErrorDetail, ...] = field(default=())

    def text(self, retry_after: int | str = "N") -> str:
        return self.message.format(retry_after=retry_after)

    def describe(self) -> str:
        return self.text()


@dataclass(frozen=True)
class GatewayError:
    status: int
    key: str
    message: str
    explanation: str


VALIDATION = ApiError(
    422,
    ErrorCode.VALIDATION_ERROR,
    "The request is invalid.",
    example_details=(
        ErrorDetail(loc=["body", "transcript"], msg="Field required", type="missing"),
    ),
)
RATE_LIMITED = ApiError(
    429,
    ErrorCode.RATE_LIMITED,
    "Too many requests. Try again in {retry_after} seconds.",
    retry_after=True,
)
BUDGET_EXHAUSTED = ApiError(
    503,
    ErrorCode.DAILY_BUDGET_EXHAUSTED,
    "The demo has reached its daily spending limit. Try again after midnight UTC.",
    retry_after=True,
)
MODEL_UNAVAILABLE = ApiError(
    502, ErrorCode.MODEL_UNAVAILABLE, "The model is unavailable. Try again later."
)
MODEL_OUTPUT_INVALID = ApiError(
    502, ErrorCode.MODEL_OUTPUT_INVALID, "The model's output failed validation twice. Try again."
)
MODEL_REFUSED = ApiError(
    422, ErrorCode.MODEL_REFUSED, "The model declined to analyse this transcript."
)
EXTRACTION_FAILED = ApiError(
    502, ErrorCode.EXTRACTION_FAILED, "The transcript could not be analysed."
)
UPLOADS_UNAVAILABLE = ApiError(
    503, ErrorCode.UPLOADS_UNAVAILABLE, "Audio uploads are not available."
)
UPLOAD_NOT_FOUND = ApiError(
    404, ErrorCode.UPLOAD_NOT_FOUND, "No upload with that id. It may have expired."
)
SAMPLE_NOT_FOUND = ApiError(404, ErrorCode.SAMPLE_NOT_FOUND, "No sample clip with that id.")
AUDIO_TOO_LONG = ApiError(422, ErrorCode.AUDIO_TOO_LONG, "The recording is longer than 60 seconds.")
AUDIO_INVALID = ApiError(422, ErrorCode.AUDIO_INVALID, "The audio is not a 16 kHz mono 16-bit WAV.")
JOBS_UNAVAILABLE = ApiError(503, ErrorCode.JOBS_UNAVAILABLE, "Jobs are not available.")
JOB_NOT_FOUND = ApiError(404, ErrorCode.JOB_NOT_FOUND, "No job with that id. It may have expired.")
JOB_NOT_FINISHED = ApiError(
    409, ErrorCode.JOB_NOT_FINISHED, "The job has no results to give feedback on."
)
SPAN_NOT_FOUND = ApiError(404, ErrorCode.SPAN_NOT_FOUND, "The job has no span with that index.")
IMPORTS_DISABLED = ApiError(404, ErrorCode.IMPORTS_DISABLED, "Imports are disabled")
BATCH_EXISTS = ApiError(409, ErrorCode.BATCH_EXISTS, "The batch already exists")
INVALID_IMPORT_OPTIONS = ApiError(
    422, ErrorCode.INVALID_IMPORT_OPTIONS, "The batch name or provenance breaks a rule"
)
BATCH_EMPTY = ApiError(422, ErrorCode.BATCH_EMPTY, "The batch is empty")
# Same code as VALIDATION, raised when an imported item breaks a rule rather than the request shape.
BATCH_VALIDATION = ApiError(
    422,
    ErrorCode.VALIDATION_ERROR,
    "A field is missing or the content is over the size cap",
)

REGISTRY: tuple[ApiError, ...] = (
    VALIDATION,
    RATE_LIMITED,
    BUDGET_EXHAUSTED,
    MODEL_UNAVAILABLE,
    MODEL_OUTPUT_INVALID,
    MODEL_REFUSED,
    EXTRACTION_FAILED,
    UPLOADS_UNAVAILABLE,
    UPLOAD_NOT_FOUND,
    SAMPLE_NOT_FOUND,
    AUDIO_TOO_LONG,
    AUDIO_INVALID,
    JOBS_UNAVAILABLE,
    JOB_NOT_FOUND,
    JOB_NOT_FINISHED,
    SPAN_NOT_FOUND,
    IMPORTS_DISABLED,
    BATCH_EXISTS,
    INVALID_IMPORT_OPTIONS,
    BATCH_EMPTY,
    BATCH_VALIDATION,
)

FORBIDDEN = GatewayError(
    403,
    "forbidden",
    "Forbidden",
    "The Authorization header is missing or is not the site password. API Gateway's authorizer "
    "answers before the request reaches the app.",
)
GATEWAY_TIMEOUT = GatewayError(
    504,
    "gateway_timeout",
    "Gateway Timeout",
    "The request took longer than API Gateway's 29 seconds. API Gateway answers, not the app.",
)

RATE_LIMIT_HEADERS: dict[str, Any] = {
    "ratelimit-limit": {
        "description": "Requests allowed per window for this rule.",
        "schema": {"type": "integer"},
    },
    "ratelimit-remaining": {
        "description": "Requests left in the current window.",
        "schema": {"type": "integer"},
    },
    "ratelimit-reset": {
        "description": "Seconds until the window resets.",
        "schema": {"type": "integer"},
    },
}
RETRY_AFTER_HEADER: dict[str, Any] = {
    "Retry-After": {
        "description": "Seconds to wait before trying again.",
        "schema": {"type": "integer"},
    }
}


def _app_error_response(errors: list[ApiError]) -> dict[str, Any]:
    lines = [f"- `{e.code}`: {e.describe()}" for e in errors]
    examples: dict[str, Any] = {}
    for e in errors:
        key = str(e.code)
        suffix = 2
        while key in examples:
            key = f"{e.code}_{suffix}"
            suffix += 1
        examples[key] = {
            "summary": e.describe(),
            "value": {
                "error": {
                    "code": str(e.code),
                    "message": e.text(30),
                    "details": [d.model_dump() for d in e.example_details],
                }
            },
        }
    response: dict[str, Any] = {
        "model": ErrorResponse,
        "description": "\n".join(lines),
        "content": {"application/json": {"examples": examples}},
    }
    if any(e.retry_after for e in errors):
        response["headers"] = RETRY_AFTER_HEADER
    return response


def _gateway_response(error: GatewayError) -> dict[str, Any]:
    return {
        "model": GatewayErrorResponse,
        "description": error.explanation,
        "content": {
            "application/json": {
                "examples": {error.key: {"value": {"message": error.message}}},
            }
        },
    }


def route_responses(
    *,
    errors: tuple[ApiError, ...] = (),
    gateway: tuple[GatewayError, ...] = (FORBIDDEN,),
    limited_success: int | None = None,
) -> dict[int | str, dict[str, Any]]:
    """The `responses=` for one route: its app errors grouped by status, the gateway errors, and
    the rate-limit headers on the success response when the route counts against a limit."""
    by_status: dict[int, list[ApiError]] = {}
    for error in errors:
        by_status.setdefault(error.status, []).append(error)
    responses: dict[int | str, dict[str, Any]] = {
        status: _app_error_response(group) for status, group in sorted(by_status.items())
    }
    for gateway_error in gateway:
        responses[gateway_error.status] = _gateway_response(gateway_error)
    if limited_success is not None:
        responses[limited_success] = {"headers": RATE_LIMIT_HEADERS}
    return responses
