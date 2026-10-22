"""The daily spend cap: stores, the cap itself and the Transcribe cost estimate."""

import logging
from collections.abc import Iterator

import boto3
import pytest
from botocore.stub import Stubber

from commitment_tracker.guardrails.spend import (
    DailyBudgetExhausted,
    DynamoSpendStore,
    MemorySpendStore,
    SpendCap,
    SpendStore,
    transcribe_cost_usd,
)

TABLE = "guardrails"
MIDNIGHT = 1_761_004_800.0  # 2025-10-21 00:00:00 UTC
NOON = MIDNIGHT + 12 * 3600
DAY = "2025-10-21"


class Clock:
    def __init__(self, now: float = NOON) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FailingStore:
    def total_micros(self, day: str) -> int:
        raise RuntimeError("table unavailable")

    def add_micros(self, day: str, micros: int, expires_at: int) -> int:
        raise RuntimeError("table unavailable")


# --- Cost estimate -------------------------------------------------------------------------------


def test_transcribe_is_billed_per_second() -> None:
    assert transcribe_cost_usd(60_000) == pytest.approx(0.024)
    assert transcribe_cost_usd(30_000) == pytest.approx(0.012)
    assert transcribe_cost_usd(0) == 0


# --- Stores --------------------------------------------------------------------------------------


def test_memory_store_adds_per_day() -> None:
    store = MemorySpendStore()
    assert store.total_micros(DAY) == 0
    assert store.add_micros(DAY, 2_000_000, 0) == 2_000_000
    assert store.add_micros(DAY, 500_000, 0) == 2_500_000
    assert store.add_micros("2025-10-22", 1, 0) == 1
    assert store.total_micros(DAY) == 2_500_000


@pytest.fixture
def dynamo() -> Iterator[tuple[DynamoSpendStore, Stubber]]:
    client = boto3.client(
        "dynamodb",
        region_name="us-east-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with Stubber(client) as stub:
        yield DynamoSpendStore(client, TABLE), stub
        stub.assert_no_pending_responses()


def test_dynamo_store_adds_atomically_with_a_ttl(
    dynamo: tuple[DynamoSpendStore, Stubber],
) -> None:
    store, stub = dynamo
    stub.add_response(
        "update_item",
        {"Attributes": {"usd_micros": {"N": "7000000"}}},
        {
            "TableName": TABLE,
            "Key": {"pk": {"S": f"spend#{DAY}"}},
            "UpdateExpression": "ADD usd_micros :n SET expires_at = :expires",
            "ExpressionAttributeValues": {":n": {"N": "25000"}, ":expires": {"N": "1761300000"}},
            "ReturnValues": "UPDATED_NEW",
        },
    )

    assert store.add_micros(DAY, 25_000, 1_761_300_000) == 7_000_000


def test_dynamo_store_reads_a_total_consistently(
    dynamo: tuple[DynamoSpendStore, Stubber],
) -> None:
    store, stub = dynamo
    stub.add_response(
        "get_item",
        {"Item": {"pk": {"S": f"spend#{DAY}"}, "usd_micros": {"N": "123"}}},
        {"TableName": TABLE, "Key": {"pk": {"S": f"spend#{DAY}"}}, "ConsistentRead": True},
    )
    stub.add_response("get_item", {})

    assert store.total_micros(DAY) == 123
    assert store.total_micros(DAY) == 0


def test_dynamo_store_fails_when_no_total_comes_back(
    dynamo: tuple[DynamoSpendStore, Stubber],
) -> None:
    store, stub = dynamo
    stub.add_response("update_item", {"Attributes": {}})
    with pytest.raises(RuntimeError, match="total"):
        store.add_micros(DAY, 1, 0)


def test_both_stores_satisfy_the_protocol() -> None:
    stores: list[SpendStore] = [MemorySpendStore(), FailingStore()]
    assert len(stores) == 2


# --- The cap -------------------------------------------------------------------------------------


def cap(
    store: SpendStore | None = None, budget: float = 5.0, clock: Clock | None = None
) -> SpendCap:
    return SpendCap(store or MemorySpendStore(), budget, clock=clock or Clock())


def test_work_is_allowed_until_the_budget_is_reached() -> None:
    spend = cap(budget=1.0)
    spend.check()
    spend.record(0.6)
    spend.check()
    spend.record(0.4)  # exactly the budget
    with pytest.raises(DailyBudgetExhausted):
        spend.check()


def test_a_refusal_says_when_the_day_ends() -> None:
    spend = cap(budget=1.0, clock=Clock(NOON))
    spend.record(1.0)
    with pytest.raises(DailyBudgetExhausted) as caught:
        spend.check()
    assert caught.value.retry_after == 12 * 3600


def test_the_budget_resets_at_utc_midnight() -> None:
    clock = Clock(MIDNIGHT + 86_399)
    spend = cap(budget=1.0, clock=clock)
    spend.record(1.0)
    with pytest.raises(DailyBudgetExhausted):
        spend.check()

    clock.now = MIDNIGHT + 86_400  # the next day

    spend.check()


def test_spending_is_summed_in_micro_dollars() -> None:
    store = MemorySpendStore()
    spend = cap(store)
    for _ in range(3):
        spend.record(0.1)
    assert store.total_micros(DAY) == 300_000
    assert spend.today_usd() == pytest.approx(0.3)


@pytest.mark.parametrize("amount", [-0.01, float("nan"), float("inf")])
def test_record_rejects_amounts_that_are_not_money(amount: float) -> None:
    with pytest.raises(ValueError, match="amount"):
        cap().record(amount)


def test_recording_nothing_is_a_no_op() -> None:
    store = MemorySpendStore()
    cap(store).record(0.0)
    assert store.total_micros(DAY) == 0


def test_the_budget_must_be_positive() -> None:
    with pytest.raises(ValueError, match="budget"):
        cap(budget=0)


def test_a_failing_store_lets_work_through_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    spend = cap(FailingStore())

    with caplog.at_level(logging.WARNING):
        spend.check()
        spend.record(1.0)

    assert caplog.text.count("spend store failed") == 2


def test_the_running_total_is_logged_without_money_detail_per_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        cap(budget=5.0).record(1.0)
    assert "spend_total" in caplog.text
    assert "fraction=0.20" in caplog.text
