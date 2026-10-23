"""The API applies the limiter per route and answers 429 with Retry-After."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from commitment_tracker.api.app import create_app
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.guardrails.ratelimit import Limit, MemoryRateLimitStore, RateLimiter
from tests.fakes import FakeAdapter, reply
from tests.test_api import BODY, GOOD_OUTPUT, FakeSigner

NOW = 1_761_000_030.0  # 30 s before the 60 s window ends


def client_with(*replies: Any, **limits: Limit) -> TestClient:
    extractor = Extractor(FakeAdapter(*replies), load_prompt("v1"))
    limiter = RateLimiter(MemoryRateLimitStore(), limits, clock=lambda: NOW)
    return TestClient(create_app(extractor=extractor, uploads=FakeSigner(), limiter=limiter))


def test_the_nth_plus_one_request_gets_429_with_retry_after() -> None:
    client = client_with(uploads=Limit(max=2, window_seconds=60))

    codes = [client.post("/uploads").status_code for _ in range(3)]

    assert codes == [200, 200, 429]
    refused = client.post("/uploads")
    assert refused.json()["error"]["code"] == "rate_limited"
    assert refused.headers["retry-after"] == "30"
    assert "30" in refused.json()["error"]["message"]


def test_successful_responses_report_the_budget() -> None:
    client = client_with(uploads=Limit(max=5, window_seconds=60))

    headers = client.post("/uploads").headers

    assert headers["ratelimit-limit"] == "5"
    assert headers["ratelimit-remaining"] == "4"
    assert headers["ratelimit-reset"] == "30"


def test_routes_have_separate_budgets() -> None:
    client = client_with(
        reply(GOOD_OUTPUT),
        uploads=Limit(max=1, window_seconds=60),
        analyze=Limit(max=1, window_seconds=60),
    )
    assert client.post("/uploads").status_code == 200
    assert client.post("/uploads").status_code == 429
    assert client.post("/analyze", json=BODY).status_code == 200
    assert client.post("/analyze", json=BODY).status_code == 429


def test_invalid_requests_count_too() -> None:
    client = client_with(analyze=Limit(max=1, window_seconds=60))

    assert client.post("/analyze", json={}).status_code == 422
    assert client.post("/analyze", json={}).status_code == 429


def test_a_changing_x_forwarded_for_does_not_reset_the_budget() -> None:
    client = client_with(uploads=Limit(max=1, window_seconds=60))

    first = client.post("/uploads", headers={"x-forwarded-for": "1.1.1.1"})
    second = client.post("/uploads", headers={"x-forwarded-for": "2.2.2.2"})

    assert (first.status_code, second.status_code) == (200, 429)


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/health"), ("get", "/openapi.json")],
)
def test_other_routes_are_not_limited(method: str, path: str) -> None:
    client = client_with(uploads=Limit(max=1, window_seconds=60))
    for _ in range(3):
        assert getattr(client, method)(path).status_code == 200


def test_without_a_limiter_nothing_is_limited() -> None:
    extractor = Extractor(FakeAdapter(), load_prompt("v1"))
    client = TestClient(create_app(extractor=extractor, uploads=FakeSigner()))
    assert all(client.post("/uploads").status_code == 200 for _ in range(30))
