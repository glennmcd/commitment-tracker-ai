"""Request guards the route modules share: the rate limit and the daily spend cap, and the error
response they answer with. Each guard runs before the body is validated."""

from typing import Any

from fastapi import Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from commitment_tracker.api.errors import ApiError, ErrorBody, ErrorDetail, ErrorResponse
from commitment_tracker.guardrails.ratelimit import RateLimiter, client_ip
from commitment_tracker.guardrails.spend import SpendCap


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


def error_response(
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
