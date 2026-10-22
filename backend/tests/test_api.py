"""The HTTP API through FastAPI's TestClient, with the extractor on a fake adapter."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from commitment_tracker.api.app import create_app
from commitment_tracker.extractor.errors import (
    ModelOutputInvalid,
    ModelRefused,
    ModelUnavailable,
)
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.model_output import ModelOutput
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.schemas import MAX_TURNS
from commitment_tracker.settings import Settings
from tests.fakes import FakeAdapter, reply

SECRET = "pricing-is-42"
BODY: dict[str, Any] = {
    "transcript": [
        {"speaker": "A", "text": "Can you resend the invoice?"},
        {"speaker": "B", "text": "Sure, I'll do it this afternoon."},
    ],
    "call_date": "2026-10-21",
}
GOOD_OUTPUT = ModelOutput.model_validate(
    {
        "spans": [
            {
                "turn_index": 1,
                "label": "COMMITMENT",
                "owner": "B",
                "recipient": "A",
                "action": "resend the invoice",
                "due": {"raw": "this afternoon", "precision_hint": "day"},
                "condition": None,
                "confidence": 0.93,
                "quote": "Sure, I'll do it this afternoon.",
                "rationale": "B agrees to A's request with a time.",
                "ambiguous": False,
            }
        ]
    }
)


def client_for(*replies: Any, model: str = "claude-opus-5-5") -> TestClient:
    extractor = Extractor(FakeAdapter(*replies, model=model), load_prompt("v1"))
    return TestClient(create_app(extractor=extractor))


# --- Health --------------------------------------------------------------------------------------


def test_health_reports_model_and_prompt() -> None:
    response = client_for().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "claude-opus-5-5", "prompt_version": "v1"}


# --- Analyze -------------------------------------------------------------------------------------


def test_analyze_returns_validated_spans() -> None:
    response = client_for(reply(GOOD_OUTPUT, served_by="claude-opus-5-5")).post(
        "/analyze", json=BODY
    )
    assert response.status_code == 200
    body = response.json()
    (span,) = body["spans"]
    assert span["label"] == "COMMITMENT"
    assert span["in_ledger"] is True
    assert span["soft"] is False
    assert span["due"] == {"raw": "this afternoon", "resolved": "2026-10-21", "precision": "day"}
    assert body["metadata"]["model"] == "claude-opus-5-5"
    assert body["metadata"]["attempts"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "transcript": []},
        {**BODY, "transcript": [{"speaker": "A", "text": SECRET}] * (MAX_TURNS + 1)},
        {**BODY, "transcript": [{"speaker": "A", "text": SECRET * 2_000}]},
        {**BODY, "call_date": "21/10/2026"},
        {**BODY, "surprise": SECRET},
        {"transcript": [{"speaker": "A", "text": SECRET}]},
    ],
)
def test_invalid_requests_get_422_without_echoing_input(body: dict[str, Any]) -> None:
    response = client_for().post("/analyze", json=body)
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["details"], "field-level details are returned"
    assert all("input" not in detail for detail in payload["error"]["details"])
    assert SECRET not in response.text


def test_malformed_json_gets_422() -> None:
    response = client_for().post(
        "/analyze", content=b'{"transcript": [', headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ModelUnavailable("RateLimitError (HTTP 429)"), 502, "model_unavailable"),
        (ModelRefused("cyber"), 422, "model_refused"),
    ],
)
def test_model_failures_map_to_error_responses(error: Exception, status: int, code: str) -> None:
    response = client_for(error).post("/analyze", json=BODY)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_invalid_model_output_twice_is_a_502() -> None:
    response = client_for(reply("nope"), reply("still nope")).post("/analyze", json=BODY)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "model_output_invalid"


def test_error_messages_are_fixed_text() -> None:
    # Internal error detail (field paths, SDK class names) stays in the logs, not the response.
    response = client_for(ModelOutputInvalid("spans.0.quote: bad")).post("/analyze", json=BODY)
    assert "spans.0" not in response.text


def test_no_log_line_contains_transcript_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    body = {**BODY, "transcript": [*BODY["transcript"], {"speaker": "A", "text": SECRET}]}
    client = client_for(reply(GOOD_OUTPUT))
    client.post("/analyze", json=body)
    client.post("/analyze", json={**body, "transcript": []})
    assert any("analyze" in r.getMessage() for r in caplog.records)
    assert all(SECRET not in r.getMessage() for r in caplog.records)


# --- Wiring from settings ------------------------------------------------------------------------


def test_app_builds_the_anthropic_extractor_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings(_env_file=None, extractor_model="claude-haiku-5-5", extractor_effort="low")
    with TestClient(create_app(settings=s)) as client:  # the lifespan builds the extractor
        assert client.get("/health").json()["model"] == "claude-haiku-5-5"


# --- OpenAPI -------------------------------------------------------------------------------------


def test_openapi_documents_the_contract() -> None:
    spec = client_for().get("/openapi.json").json()
    analyze = spec["paths"]["/analyze"]["post"]
    assert analyze["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/AnalyzeRequest"
    )
    assert set(analyze["responses"]) >= {"200", "422", "502"}
    assert {"AnalyzeRequest", "AnalyzeResponse", "Span", "Due", "Metadata", "ErrorResponse"} <= set(
        spec["components"]["schemas"]
    )
    assert "/health" in spec["paths"]


def test_production_startup_makes_app_logs_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    # uvicorn configures only its own loggers; without this the analyze lines are dropped.
    package = logging.getLogger("commitment_tracker")
    monkeypatch.setattr(package, "handlers", [])
    monkeypatch.setattr(package, "level", logging.NOTSET)
    s = Settings(_env_file=None)
    with TestClient(create_app(settings=s)):
        assert package.handlers
        assert package.getEffectiveLevel() == logging.INFO
