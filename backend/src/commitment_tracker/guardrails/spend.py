"""The daily spend cap, enforced by the app because AWS Budgets lags by hours and never sees
Anthropic charges (docs/plans/part-2-audio-and-deploy.md).

One counter per UTC day, in micro-dollars so DynamoDB can add integers atomically. Transcribe's
estimated cost is added when a job starts and the model's cost after each call; new work is refused
once the day's total reaches the budget. Unknown costs (a model with no price) add nothing. If the
store fails, work goes ahead and the failure is logged: the monthly AWS budget kill switch is the
backstop. Logs carry totals, never request content.
"""

import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from types_boto3_dynamodb import DynamoDBClient

logger = logging.getLogger(__name__)

# Standard batch rate, billed per second with no minimum (the plan's cost estimate).
TRANSCRIBE_USD_PER_MINUTE = 0.024
_MICROS = 1_000_000
_TTL_DAYS = 2  # a day's item lives this long past its midnight before DynamoDB may delete it


def transcribe_cost_usd(duration_ms: int) -> float:
    return duration_ms / 60_000 * TRANSCRIBE_USD_PER_MINUTE


class DailyBudgetExhausted(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("the daily budget is used up")
        self.retry_after = retry_after  # seconds until UTC midnight


class SpendStore(Protocol):
    def total_micros(self, day: str) -> int: ...

    def add_micros(self, day: str, micros: int, expires_at: int) -> int:
        """Add to the day's total atomically and return the new total."""
        ...


class MemorySpendStore:
    def __init__(self) -> None:
        self._totals: dict[str, int] = {}

    def total_micros(self, day: str) -> int:
        return self._totals.get(day, 0)

    def add_micros(self, day: str, micros: int, expires_at: int) -> int:
        self._totals[day] = self._totals.get(day, 0) + micros
        return self._totals[day]


class DynamoSpendStore:
    """One item per day in the guardrails table (string key `pk`, TTL `expires_at`)."""

    def __init__(self, client: "DynamoDBClient", table_name: str) -> None:
        self._client = client
        self._table = table_name

    @staticmethod
    def _key(day: str) -> dict[str, dict[str, str]]:
        return {"pk": {"S": f"spend#{day}"}}

    def total_micros(self, day: str) -> int:
        item = self._client.get_item(
            TableName=self._table, Key=self._key(day), ConsistentRead=True
        ).get("Item")
        return int(item["usd_micros"]["N"]) if item and "usd_micros" in item else 0

    def add_micros(self, day: str, micros: int, expires_at: int) -> int:
        response = self._client.update_item(
            TableName=self._table,
            Key=self._key(day),
            UpdateExpression="ADD usd_micros :n SET expires_at = :expires",
            ExpressionAttributeValues={
                ":n": {"N": str(micros)},
                ":expires": {"N": str(expires_at)},
            },
            ReturnValues="UPDATED_NEW",
        )
        total = response.get("Attributes", {}).get("usd_micros", {}).get("N")
        if total is None:
            raise RuntimeError("DynamoDB did not return a total for the spend counter")
        return int(total)


class SpendCap:
    def __init__(
        self,
        store: SpendStore,
        daily_budget_usd: float,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not daily_budget_usd > 0:
            raise ValueError("the daily budget must be positive")
        self._store = store
        self._budget_micros = round(daily_budget_usd * _MICROS)
        self._budget_usd = daily_budget_usd
        self._clock = clock

    def _today(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), UTC)

    def _day(self) -> str:
        return self._today().date().isoformat()

    def _next_midnight(self) -> datetime:
        today = self._today()
        return datetime.combine(today.date() + timedelta(days=1), datetime.min.time(), UTC)

    def today_usd(self) -> float:
        return self._store.total_micros(self._day()) / _MICROS

    def check(self) -> None:
        """Raise DailyBudgetExhausted when today's spending has reached the budget."""
        try:
            spent = self._store.total_micros(self._day())
        except Exception as error:
            logger.warning("spend store failed op=check error=%s", type(error).__name__)
            return
        if spent >= self._budget_micros:
            retry_after = max(1, math.ceil(self._next_midnight().timestamp() - self._clock()))
            logger.warning("daily budget exhausted spent_usd=%.4f", spent / _MICROS)
            raise DailyBudgetExhausted(retry_after)

    def record(self, amount_usd: float) -> None:
        if not math.isfinite(amount_usd) or amount_usd < 0:
            raise ValueError("amount must be a finite, non-negative number of dollars")
        micros = round(amount_usd * _MICROS)
        if micros == 0:
            return
        expires_at = int(self._next_midnight().timestamp()) + _TTL_DAYS * 86_400
        try:
            total = self._store.add_micros(self._day(), micros, expires_at)
        except Exception as error:
            logger.warning("spend store failed op=record error=%s", type(error).__name__)
            return
        logger.info(
            "spend_total usd=%.4f budget_usd=%.2f fraction=%.2f",
            total / _MICROS,
            self._budget_usd,
            total / self._budget_micros,
        )
