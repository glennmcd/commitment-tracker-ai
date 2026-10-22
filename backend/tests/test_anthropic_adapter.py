"""The Anthropic adapter against a stubbed client: the request it builds and how it reads replies.

The stub returns real SDK response types, so attribute names are checked against the installed
SDK. No request leaves the machine.
"""

import asyncio
import json
from typing import Any, cast

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from commitment_tracker.extractor.adapter import Message, ModelRequest, Usage
from commitment_tracker.extractor.anthropic_adapter import AnthropicAdapter
from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.model_output import ModelOutput

TRANSCRIPT = "<transcript>secret pricing talk</transcript>"
JSON_TEXT = '{"spans": []}'


def message(
    *,
    content: list[dict[str, Any]] | None = None,
    model: str = "claude-opus-5-5",
    stop_reason: str = "end_turn",
    stop_details: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content
            if content is not None
            else [
                {"type": "thinking", "thinking": "", "signature": "sig-abc"},
                {"type": "text", "text": JSON_TEXT},
            ],
            "stop_reason": stop_reason,
            "stop_details": stop_details,
            "usage": usage
            or {
                "input_tokens": 210,
                "output_tokens": 840,
                "cache_creation_input_tokens": None,
                "cache_read_input_tokens": 2_480,
            },
        }
    )


class StubMessages:
    def __init__(self, result: BetaMessage | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> BetaMessage:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class StubClient:
    def __init__(self, result: BetaMessage | Exception) -> None:
        self.messages = StubMessages(result)
        self.beta = self  # the adapter calls client.beta.messages.create


def adapter_for(
    result: BetaMessage | Exception, model: str = "claude-opus-5-5"
) -> tuple[AnthropicAdapter, StubMessages]:
    stub = StubClient(result)
    return AnthropicAdapter(model, client=cast(anthropic.AsyncAnthropic, stub)), stub.messages


def request(*messages: Message) -> ModelRequest:
    return ModelRequest(
        system="SYSTEM PROMPT",
        messages=messages or (Message("user", TRANSCRIPT),),
        output_model=ModelOutput,
    )


def complete(adapter: AnthropicAdapter, req: ModelRequest | None = None) -> Any:
    return asyncio.run(adapter.complete(req or request()))


# --- The request ---------------------------------------------------------------------------------


def test_request_carries_model_cached_system_schema_and_effort() -> None:
    adapter, stub = adapter_for(message())
    complete(adapter)

    (call,) = stub.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["max_tokens"] == 16_000
    assert call["system"] == [
        {"type": "text", "text": "SYSTEM PROMPT", "cache_control": {"type": "ephemeral"}}
    ]
    assert call["messages"] == [{"role": "user", "content": TRANSCRIPT}]
    assert call["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": anthropic.transform_schema(ModelOutput)},
    }
    # Forced tool use is rejected by Opus 5.5 and Sonnet 5.5; structured outputs need no tools.
    assert "tools" not in call
    assert "tool_choice" not in call
    assert "thinking" not in call  # adaptive by default; it can't be disabled on Opus 5.5


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5"])
def test_opus_and_sonnet_get_server_side_refusal_fallback(model: str) -> None:
    adapter, stub = adapter_for(message(model=model), model=model)
    complete(adapter)
    assert stub.calls[0]["fallbacks"] == "default"
    assert stub.calls[0]["betas"] == ["server-side-fallback-2026-07-01"]


def test_haiku_has_no_server_side_fallback() -> None:
    adapter, stub = adapter_for(message(model="claude-haiku-5-5"), model="claude-haiku-5-5")
    complete(adapter)
    assert "fallbacks" not in stub.calls[0]
    assert "betas" not in stub.calls[0]


def test_effort_and_max_tokens_are_configurable() -> None:
    stub = StubClient(message())
    adapter = AnthropicAdapter(
        "claude-opus-5-5",
        effort="low",
        max_tokens=4_000,
        client=cast(anthropic.AsyncAnthropic, stub),
    )
    complete(adapter)
    call = stub.messages.calls[0]
    assert (call["output_config"]["effort"], call["max_tokens"]) == ("low", 4_000)


def test_retry_passes_the_assistant_content_back_unchanged() -> None:
    adapter, stub = adapter_for(message())
    first = complete(adapter)
    retry = request(
        Message("user", TRANSCRIPT),
        Message("assistant", first.assistant_content),
        Message("user", "fix spans.0.label"),
    )
    complete(adapter, retry)
    sent = stub.calls[1]["messages"]
    assert sent[1] == {"role": "assistant", "content": list(first.assistant_content)}
    assert sent[1]["content"][0]["signature"] == "sig-abc"  # thinking blocks survive the round trip


# --- The reply -----------------------------------------------------------------------------------


def test_reply_is_read_from_the_text_block() -> None:
    adapter, _ = adapter_for(message())
    reply = complete(adapter)
    assert reply.text == JSON_TEXT
    assert reply.stop_reason == "end_turn"
    assert reply.served_by == "claude-opus-5-5"
    assert reply.refusal_category is None
    assert reply.latency_ms >= 0


def test_usage_is_mapped_and_missing_cache_counts_are_zero() -> None:
    adapter, _ = adapter_for(message())
    assert complete(adapter).usage == Usage(
        input_tokens=210,
        output_tokens=840,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=2_480,
    )


def test_served_by_reports_the_fallback_model() -> None:
    adapter, _ = adapter_for(message(model="claude-opus-5"))
    assert complete(adapter).served_by == "claude-opus-5"


def test_refusal_reports_its_category() -> None:
    adapter, _ = adapter_for(
        message(
            content=[], stop_reason="refusal", stop_details={"type": "refusal", "category": "bio"}
        )
    )
    reply = complete(adapter)
    assert (reply.stop_reason, reply.refusal_category, reply.text) == ("refusal", "bio", "")


def test_reply_without_text_block_has_empty_text() -> None:
    adapter, _ = adapter_for(
        message(content=[{"type": "thinking", "thinking": "", "signature": "s"}])
    )
    assert complete(adapter).text == ""


# --- Errors --------------------------------------------------------------------------------------

API_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (
            anthropic.RateLimitError(
                "rate limited", response=httpx2.Response(429, request=API_REQUEST), body=None
            ),
            "429",
        ),
        (
            anthropic.InternalServerError(
                "boom", response=httpx2.Response(500, request=API_REQUEST), body=None
            ),
            "500",
        ),
        (
            anthropic.BadRequestError(
                "schema too complex", response=httpx2.Response(400, request=API_REQUEST), body=None
            ),
            "400",
        ),
        (anthropic.APIConnectionError(request=API_REQUEST), "APIConnectionError"),
        (anthropic.APITimeoutError(request=API_REQUEST), "APITimeoutError"),
    ],
)
def test_api_errors_become_model_unavailable(error: Exception, fragment: str) -> None:
    adapter, _ = adapter_for(error)
    with pytest.raises(ModelUnavailable, match=fragment) as caught:
        complete(adapter)
    assert "secret pricing" not in str(caught.value)


def test_default_client_uses_a_bounded_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    adapter = AnthropicAdapter("claude-opus-5-5")
    assert adapter.client.timeout == 60.0
    assert adapter.client.max_retries == 2


# --- Through the real SDK client, over an in-memory transport ------------------------------------


def test_real_client_sends_the_beta_header_and_parses_the_reply() -> None:
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, json=message(model="claude-sonnet-5-5").model_dump())

    client = anthropic.AsyncAnthropic(
        api_key="test-key-not-real",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    adapter = AnthropicAdapter("claude-sonnet-5-5", client=client)
    reply = complete(adapter)

    (sent,) = seen
    body = json.loads(sent.content)
    assert sent.url.path == "/v1/messages"
    assert "server-side-fallback-2026-07-01" in sent.headers["anthropic-beta"]
    assert body["fallbacks"] == "default"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "betas" not in body  # sent as a header, not in the body
    assert reply.text == JSON_TEXT
    assert reply.served_by == "claude-sonnet-5-5"


def test_missing_credentials_fail_cleanly_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Without this check the SDK raises a bare TypeError at request time.
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    adapter = AnthropicAdapter("claude-opus-5-5")
    with pytest.raises(ModelUnavailable, match="no Anthropic credentials"):
        complete(adapter)
