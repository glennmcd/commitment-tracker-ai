"""Fixed-window rate limiting per client address, ported from FlakeHunter.

A counter is one item per key and window. On Lambda every concurrent invocation is its own process,
so production counts in DynamoDB with an atomic `ADD hits 1`; the in-memory store serves tests and
local runs. If the store fails the request is let through and the failure is logged (a broken
counter must not take the demo down; the stage throttle and the daily spend cap still apply). The
client is the address API Gateway reports, never `X-Forwarded-For`, which the caller controls.
Logs name the rule, never the address.
"""

import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from starlette.requests import Request

if TYPE_CHECKING:
    from types_boto3_dynamodb import DynamoDBClient

logger = logging.getLogger(__name__)

# How long past the end of its window a counter lives before DynamoDB's TTL may delete it.
TTL_SLACK_SECONDS = 120


@dataclass(frozen=True)
class Limit:
    max: int  # requests allowed per client in one window
    window_seconds: int

    def __post_init__(self) -> None:
        if self.max < 1 or self.window_seconds < 1:
            raise ValueError("a limit's max and window_seconds must be positive")


# The rule names are the routes' names in the API. Uploads and jobs are separate budgets.
DEFAULT_LIMITS: dict[str, Limit] = {
    "uploads": Limit(max=20, window_seconds=3600),
    "jobs": Limit(max=20, window_seconds=3600),
    "analyze": Limit(max=30, window_seconds=3600),
    "feedback": Limit(max=120, window_seconds=3600),
    "job_status": Limit(max=120, window_seconds=60),
}


@dataclass(frozen=True)
class RateHit:
    count: int  # requests counted for this key in the current window, this one included
    reset_at: float  # epoch seconds at which the window ends and the count starts again


class RateLimitStore(Protocol):
    def hit(self, key: str, window_seconds: int, now: float | None = None) -> RateHit: ...


def _window(now: float, window_seconds: int) -> tuple[int, int]:
    bucket = int(now // window_seconds)
    return bucket, (bucket + 1) * window_seconds


class MemoryRateLimitStore:
    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, int]] = {}  # id -> (count, reset_at)

    @property
    def size(self) -> int:
        return len(self._counts)

    def hit(self, key: str, window_seconds: int, now: float | None = None) -> RateHit:
        moment = time.time() if now is None else now
        bucket, reset_at = _window(moment, window_seconds)
        item = f"{key}#{bucket}"
        count = self._counts.get(item, (0, reset_at))[0] + 1
        self._counts[item] = (count, reset_at)
        # Drop windows that have ended so the dict does not grow without bound.
        self._counts = {k: v for k, v in self._counts.items() if v[1] > moment}
        return RateHit(count=count, reset_at=reset_at)


class DynamoRateLimitStore:
    """One item per key and window in the guardrails table (string key `pk`, TTL `expires_at`)."""

    def __init__(self, client: "DynamoDBClient", table_name: str) -> None:
        self._client = client
        self._table = table_name

    def hit(self, key: str, window_seconds: int, now: float | None = None) -> RateHit:
        moment = time.time() if now is None else now
        bucket, reset_at = _window(moment, window_seconds)
        response = self._client.update_item(
            TableName=self._table,
            Key={"pk": {"S": f"{key}#{bucket}"}},
            UpdateExpression="ADD hits :one SET expires_at = :expires",
            ExpressionAttributeValues={
                ":one": {"N": "1"},
                ":expires": {"N": str(reset_at + TTL_SLACK_SECONDS)},
            },
            ReturnValues="UPDATED_NEW",
        )
        count = response.get("Attributes", {}).get("hits", {}).get("N")
        if count is None:
            raise RuntimeError("DynamoDB did not return a count for the rate limit counter")
        return RateHit(count=int(count), reset_at=reset_at)


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until the window ends


class RateLimiter:
    def __init__(
        self,
        store: RateLimitStore,
        limits: Mapping[str, Limit] | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._limits = dict(DEFAULT_LIMITS if limits is None else limits)
        self._clock = clock

    def check(self, rule: str, client: str) -> RateDecision:
        """Count one request from `client` under `rule`; KeyError for a rule that isn't defined."""
        limit = self._limits[rule]
        now = self._clock()
        try:
            hit = self._store.hit(f"rl#{rule}#{client}", limit.window_seconds, now)
        except Exception as error:
            logger.warning("rate limit store failed rule=%s error=%s", rule, type(error).__name__)
            return RateDecision(True, limit.max, limit.max, limit.window_seconds)
        return RateDecision(
            allowed=hit.count <= limit.max,
            limit=limit.max,
            remaining=max(0, limit.max - hit.count),
            retry_after=max(1, math.ceil(hit.reset_at - now)),
        )


def client_ip(request: Request) -> str:
    """The address API Gateway saw. Locally, with no gateway event, the socket's peer."""
    event: Any = request.scope.get("aws.event")
    if isinstance(event, Mapping):
        try:
            source = event["requestContext"]["http"]["sourceIp"]
        except (KeyError, TypeError):
            source = None
        if isinstance(source, str) and source:
            return source
    return request.client.host if request.client is not None else "unknown"
