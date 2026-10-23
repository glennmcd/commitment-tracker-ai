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
from commitment_tracker.jobs.audio import MAX_AUDIO_BYTES
from commitment_tracker.jobs.uploads import UploadTicket
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


def _source_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("request ")]


def test_x_source_header_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    client_for(reply(GOOD_OUTPUT)).post("/analyze", json=BODY, headers={"X-Source": "alice-2026"})
    assert _source_lines(caplog) == ["request method=POST path=/analyze pwsource=alice-2026"]


@pytest.mark.parametrize("value", ["a b", "x" * 65, "<script>", "al/ice"])
def test_unusable_x_source_is_logged_as_invalid(
    caplog: pytest.LogCaptureFixture, value: str
) -> None:
    caplog.set_level(logging.INFO)
    client_for().get("/health", headers={"X-Source": value})
    assert _source_lines(caplog) == ["request method=GET path=/health pwsource=invalid"]


def test_the_password_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client_for(reply(GOOD_OUTPUT)).post(
        "/analyze", json=BODY, headers={"Authorization": "hunter2-pass", "X-Source": "alice"}
    )
    assert all("hunter2-pass" not in r.getMessage() for r in caplog.records)


def test_no_x_source_means_no_source_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    client_for().get("/health")
    assert _source_lines(caplog) == []


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


def test_openapi_version_is_the_api_contract_version_not_the_release() -> None:
    # Releases bump commitment_tracker.__version__; the contract version changes only with the
    # request or response shape, so openapi.json (and the frontend client) stay put across releases.
    from commitment_tracker.api.app import API_VERSION

    spec = client_for().get("/openapi.json").json()
    assert spec["info"]["version"] == API_VERSION


def test_openapi_documents_the_site_password_on_every_endpoint_but_health() -> None:
    # API Gateway's Lambda authorizer enforces the password before a request reaches the app, so the
    # app itself never checks it; the scheme is published so clients know to send the header.
    spec = client_for().get("/openapi.json").json()

    assert spec["components"]["securitySchemes"]["SitePassword"] == {
        "type": "apiKey",
        "in": "header",
        "name": "Authorization",
        "description": spec["components"]["securitySchemes"]["SitePassword"]["description"],
    }
    assert spec["security"] == [{"SitePassword": []}]
    assert spec["paths"]["/health"]["get"]["security"] == []
    for path, operations in spec["paths"].items():
        for operation in operations.values():
            if path != "/health":
                assert "security" not in operation, path


def test_openapi_is_built_once_and_stays_the_same() -> None:
    app = create_app(extractor=Extractor(FakeAdapter(), load_prompt("v1")))
    assert app.openapi() is app.openapi()


# --- Uploads -------------------------------------------------------------------------------------


class FakeSigner:
    def __init__(self) -> None:
        self.calls = 0

    def presign(self) -> UploadTicket:
        self.calls += 1
        return UploadTicket(
            upload_id="a" * 32,
            key=f"uploads/{'a' * 32}.wav",
            url="https://audio-bucket.s3.us-east-2.amazonaws.com/",
            fields={"key": f"uploads/{'a' * 32}.wav", "policy": "p"},
            expires_in=300,
        )


def uploads_client(signer: FakeSigner | None) -> TestClient:
    extractor = Extractor(FakeAdapter(), load_prompt("v1"))
    return TestClient(create_app(extractor=extractor, uploads=signer))


def test_post_uploads_returns_the_presigned_form() -> None:
    signer = FakeSigner()
    response = uploads_client(signer).post("/uploads")
    assert response.status_code == 200
    assert response.json() == {
        "upload_id": "a" * 32,
        "url": "https://audio-bucket.s3.us-east-2.amazonaws.com/",
        "fields": {"key": f"uploads/{'a' * 32}.wav", "policy": "p"},
        "max_bytes": MAX_AUDIO_BYTES,
        "expires_in": 300,
    }
    assert signer.calls == 1


def test_post_uploads_without_storage_configured_is_503() -> None:
    response = uploads_client(None).post("/uploads")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "uploads_unavailable"


def test_uploads_log_only_the_id(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        uploads_client(FakeSigner()).post("/uploads")
    assert "policy" not in caplog.text
