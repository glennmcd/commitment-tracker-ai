"""Fixed-window rate limiting: the stores, the limiter and how the API derives a client."""

import logging
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from starlette.requests import Request

from commitment_tracker.guardrails.ratelimit import (
    DEFAULT_LIMITS,
    DynamoRateLimitStore,
    Limit,
    MemoryRateLimitStore,
    RateHit,
    RateLimiter,
    RateLimitStore,
    client_ip,
)

TABLE = "guardrails"
NOW = 1_761_000_030.0  # 30 s into a 60 s window that began at 1_761_000_000


class FailingStore:
    def hit(self, key: str, window_seconds: int, now: float | None = None) -> RateHit:
        raise RuntimeError("table unavailable")


# --- Memory store --------------------------------------------------------------------------------


def test_memory_store_counts_within_a_window() -> None:
    store = MemoryRateLimitStore()
    counts = [store.hit("k", 60, now=NOW + i).count for i in range(3)]
    assert counts == [1, 2, 3]


def test_memory_store_starts_over_in_the_next_window() -> None:
    store = MemoryRateLimitStore()
    store.hit("k", 60, now=NOW)
    store.hit("k", 60, now=NOW)

    assert store.hit("k", 60, now=NOW + 30).count == 1


def test_memory_store_counts_keys_separately_and_reports_the_window_end() -> None:
    store = MemoryRateLimitStore()
    store.hit("a", 60, now=NOW)
    hit = store.hit("b", 60, now=NOW)
    assert hit.count == 1
    assert hit.reset_at == 1_761_000_060


def test_memory_store_forgets_finished_windows() -> None:
    store = MemoryRateLimitStore()
    for i in range(5):
        store.hit(f"k{i}", 60, now=NOW)
    store.hit("later", 60, now=NOW + 3600)
    assert store.size == 1


# --- DynamoDB store ------------------------------------------------------------------------------


@pytest.fixture
def dynamo() -> Iterator[tuple[DynamoRateLimitStore, Stubber]]:
    client = boto3.client(
        "dynamodb",
        region_name="us-east-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with Stubber(client) as stub:
        yield DynamoRateLimitStore(client, TABLE), stub
        stub.assert_no_pending_responses()


def test_dynamo_store_adds_one_atomically_and_sets_a_ttl(
    dynamo: tuple[DynamoRateLimitStore, Stubber],
) -> None:
    store, stub = dynamo
    stub.add_response(
        "update_item",
        {"Attributes": {"hits": {"N": "3"}}},
        {
            "TableName": TABLE,
            "Key": {"pk": {"S": f"rl#ip:1.2.3.4#{int(NOW // 60)}"}},
            "UpdateExpression": "ADD hits :one SET expires_at = :expires",
            "ExpressionAttributeValues": {
                ":one": {"N": "1"},
                ":expires": {"N": str(1_761_000_060 + 120)},
            },
            "ReturnValues": "UPDATED_NEW",
        },
    )

    hit = store.hit("rl#ip:1.2.3.4", 60, now=NOW)

    assert hit == RateHit(count=3, reset_at=1_761_000_060)


def test_dynamo_store_fails_when_no_count_comes_back(
    dynamo: tuple[DynamoRateLimitStore, Stubber],
) -> None:
    store, stub = dynamo
    stub.add_response("update_item", {"Attributes": {}})
    with pytest.raises(RuntimeError, match="count"):
        store.hit("k", 60, now=NOW)


def test_both_stores_satisfy_the_protocol() -> None:
    stores: list[RateLimitStore] = [MemoryRateLimitStore(), FailingStore()]
    assert len(stores) == 2


# --- Limiter -------------------------------------------------------------------------------------


def limiter(store: RateLimitStore | None = None, **limits: Limit) -> RateLimiter:
    return RateLimiter(store or MemoryRateLimitStore(), limits or None, clock=lambda: NOW)


def test_it_allows_up_to_the_limit_then_refuses() -> None:
    check = limiter(jobs=Limit(max=3, window_seconds=60))

    decisions = [check.check("jobs", "1.2.3.4") for _ in range(4)]

    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions] == [2, 1, 0, 0]
    assert all(d.limit == 3 for d in decisions)


def test_a_refusal_says_when_to_retry() -> None:
    check = limiter(jobs=Limit(max=1, window_seconds=60))
    check.check("jobs", "1.2.3.4")

    refused = check.check("jobs", "1.2.3.4")

    assert not refused.allowed
    assert refused.retry_after == 30  # the window ends 30 s from NOW


def test_clients_and_rules_are_counted_separately() -> None:
    check = limiter(jobs=Limit(max=1, window_seconds=60), uploads=Limit(max=1, window_seconds=60))
    assert check.check("jobs", "1.2.3.4").allowed
    assert check.check("jobs", "5.6.7.8").allowed
    assert check.check("uploads", "1.2.3.4").allowed
    assert not check.check("jobs", "1.2.3.4").allowed


def test_a_store_failure_lets_the_request_through_and_logs_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = limiter(FailingStore(), jobs=Limit(max=1, window_seconds=60))

    with caplog.at_level(logging.WARNING):
        decision = check.check("jobs", "9.9.9.9")

    assert decision.allowed
    assert "rate limit store failed" in caplog.text
    assert "9.9.9.9" not in caplog.text


def test_an_unknown_rule_is_a_programming_error() -> None:
    with pytest.raises(KeyError):
        limiter().check("nope", "1.2.3.4")


def test_the_default_limits_follow_the_design() -> None:
    assert DEFAULT_LIMITS["uploads"] == Limit(max=20, window_seconds=3600)
    assert DEFAULT_LIMITS["jobs"] == Limit(max=20, window_seconds=3600)
    assert DEFAULT_LIMITS["analyze"] == Limit(max=30, window_seconds=3600)
    assert DEFAULT_LIMITS["job_status"] == Limit(max=120, window_seconds=60)


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Limit(max=0, window_seconds=60)
    with pytest.raises(ValueError, match="positive"):
        Limit(max=1, window_seconds=0)


# --- Client address ------------------------------------------------------------------------------


def request_with(
    scope_extra: dict[str, Any], headers: list[tuple[bytes, bytes]] | None = None
) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/jobs",
        "headers": headers or [],
        "client": ("10.0.0.1", 5000),
    }
    return Request(scope | scope_extra)


def test_the_gateway_source_ip_wins() -> None:
    aws_event = {"requestContext": {"http": {"sourceIp": "203.0.113.7"}}}
    assert client_ip(request_with({"aws.event": aws_event})) == "203.0.113.7"


def test_x_forwarded_for_is_never_trusted() -> None:
    request = request_with({}, headers=[(b"x-forwarded-for", b"6.6.6.6")])
    assert client_ip(request) == "10.0.0.1"


def test_a_malformed_gateway_event_falls_back_to_the_socket() -> None:
    assert client_ip(request_with({"aws.event": {"requestContext": {}}})) == "10.0.0.1"


def test_no_address_at_all_is_one_shared_client() -> None:
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    assert client_ip(Request(scope)) == "unknown"
