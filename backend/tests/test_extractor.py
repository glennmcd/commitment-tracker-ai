"""The extraction pipeline with a fake adapter: validation, one retry, quote check and dates."""

import asyncio
import logging
from datetime import date
from typing import Any

import pytest

from commitment_tracker.extractor.adapter import Usage
from commitment_tracker.extractor.errors import ModelOutputInvalid, ModelRefused, ModelUnavailable
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.model_output import ModelOutput
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse, Label, Precision, Turn
from tests.fakes import FakeAdapter, reply

REQUEST_TEXT = "Can you resend the invoice?"
REPLY_TEXT = "Sure, I'll do it this afternoon."
REQUEST = AnalyzeRequest(
    transcript=[Turn(speaker="A", text=REQUEST_TEXT), Turn(speaker="B", text=REPLY_TEXT)],
    call_date=date(2026, 10, 21),
)
PROMPT = load_prompt("v1")


def span(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "turn_index": 1,
        "label": "COMMITMENT",
        "owner": "B",
        "recipient": "A",
        "action": "resend the invoice",
        "due": {"raw": "this afternoon", "precision_hint": "day"},
        "condition": None,
        "confidence": 0.93,
        "quote": "I'll do it this afternoon.",
        "rationale": "B agrees to A's request with a time.",
        "ambiguous": False,
    }
    data.update(overrides)
    return data


def request_span() -> dict[str, Any]:
    return span(
        turn_index=0,
        label="REQUEST",
        owner=None,
        recipient="A",
        due={"raw": None, "precision_hint": "none"},
        quote=REQUEST_TEXT,
        rationale="A asks B to act.",
    )


def output(*spans: dict[str, Any]) -> ModelOutput:
    return ModelOutput.model_validate({"spans": list(spans)})


def analyze(adapter: FakeAdapter, request: AnalyzeRequest = REQUEST) -> AnalyzeResponse:
    return asyncio.run(Extractor(adapter, PROMPT).analyze(request))


# --- Happy path ----------------------------------------------------------------------------------


def test_returns_validated_spans_with_resolved_dates() -> None:
    adapter = FakeAdapter(reply(output(span(), request_span())))
    result = analyze(adapter)

    assert [s.label for s in result.spans] == [Label.REQUEST, Label.COMMITMENT]  # by turn
    commitment = result.spans[1]
    assert commitment.owner == "B"
    assert commitment.due.raw == "this afternoon"
    assert commitment.due.resolved == date(2026, 10, 21)
    assert commitment.due.precision is Precision.DAY
    assert commitment.in_ledger
    assert not result.spans[0].in_ledger


def test_sends_the_prompt_and_transcript() -> None:
    adapter = FakeAdapter(reply(output(request_span(), span())))
    analyze(adapter)

    (sent,) = adapter.requests
    assert sent.system == PROMPT.system
    assert sent.output_model is ModelOutput
    (message,) = sent.messages
    assert message.role == "user"
    assert REQUEST_TEXT in str(message.content)
    assert "<call_date>2026-10-21 (Wednesday)</call_date>" in str(message.content)


def test_metadata_on_a_first_time_success() -> None:
    usage = Usage(
        input_tokens=200,
        output_tokens=1_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=2_500,
    )
    adapter = FakeAdapter(
        reply(output(request_span(), span()), usage=usage, served_by="claude-opus-5-5"),
        model="claude-opus-5-5",
    )
    metadata = analyze(adapter).metadata

    assert metadata.model == "claude-opus-5-5"
    assert metadata.served_by == "claude-opus-5-5"
    assert metadata.prompt_version == "v1"
    assert metadata.attempts == 1
    assert metadata.dropped_quotes == 0
    assert (metadata.input_tokens, metadata.output_tokens) == (200, 1_000)
    assert metadata.cache_read_input_tokens == 2_500
    assert metadata.cost_usd == pytest.approx((200 * 4 + 2_500 * 0.2 + 1_000 * 20) / 1e6)
    assert metadata.latency_ms >= 0


def test_unknown_model_cost_is_null() -> None:
    adapter = FakeAdapter(reply(output(request_span(), span())))
    assert analyze(adapter).metadata.cost_usd is None


@pytest.mark.parametrize(
    ("due", "resolved", "precision"),
    [
        ({"raw": "by Friday", "precision_hint": "day"}, date(2026, 10, 23), Precision.DAY),
        ({"raw": "next week", "precision_hint": "day"}, date(2026, 10, 26), Precision.WEEK),
        ({"raw": "before the offsite", "precision_hint": "event"}, None, Precision.EVENT),
        ({"raw": "before the offsite", "precision_hint": "day"}, None, Precision.VAGUE),
        ({"raw": None, "precision_hint": "day"}, None, Precision.NONE),
        ({"raw": "  ", "precision_hint": "vague"}, None, Precision.NONE),
    ],
)
def test_due_is_resolved_by_code_not_the_model(
    due: dict[str, Any], resolved: date | None, precision: Precision
) -> None:
    adapter = FakeAdapter(reply(output(request_span(), span(due=due))))
    commitment = analyze(adapter).spans[1]
    assert (commitment.due.resolved, commitment.due.precision) == (resolved, precision)


# --- One retry -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "error_fragment"),
    [
        (reply("not json at all"), "Invalid JSON"),
        (reply('{"spans": [{"turn_index": 1}]}'), "spans.0.label"),
        (reply(output(request_span(), span()), stop_reason="max_tokens"), "max_tokens"),
        (reply(output(request_span(), span(turn_index=5))), "spans.1.turn_index"),
        (reply(output(span(label="CONDITIONAL"), request_span())), "condition is required"),
        (reply(output(span(owner=None), request_span())), "owner is required"),
    ],
)
def test_invalid_reply_is_retried_once_with_the_errors(first: Any, error_fragment: str) -> None:
    second = reply(output(request_span(), span()))
    adapter = FakeAdapter(first, second)
    result = analyze(adapter)

    assert result.metadata.attempts == 2
    assert len(result.spans) == 2
    retry = adapter.requests[1]
    user, assistant, correction = retry.messages
    assert user == adapter.requests[0].messages[0]
    assert assistant.role == "assistant"
    assert assistant.content is first.assistant_content  # appended unchanged
    assert correction.role == "user"
    assert error_fragment in str(correction.content)


def test_retry_message_names_fields_not_transcript_text() -> None:
    bad = output(span(quote=REPLY_TEXT, confidence=0.5, label="CONDITIONAL"))
    adapter = FakeAdapter(reply(bad), reply(output(request_span(), span())))
    analyze(adapter)
    correction = str(adapter.requests[1].messages[2].content)
    assert REPLY_TEXT not in correction
    assert REQUEST_TEXT not in correction


def test_usage_and_cost_add_up_across_attempts() -> None:
    usage = Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=1_000,
    )
    adapter = FakeAdapter(
        reply("{", usage=usage, served_by="claude-sonnet-5-5"),
        reply(output(request_span(), span()), usage=usage, served_by="claude-sonnet-5-5"),
        model="claude-sonnet-5-5",
    )
    metadata = analyze(adapter).metadata
    assert (metadata.input_tokens, metadata.output_tokens) == (200, 100)
    assert (metadata.cache_creation_input_tokens, metadata.cache_read_input_tokens) == (20, 2_000)
    one = (100 * 2.0 + 10 * 2.5 + 1_000 * 0.1 + 50 * 10.0) / 1e6
    assert metadata.cost_usd == pytest.approx(2 * one)


def test_two_invalid_replies_raise() -> None:
    adapter = FakeAdapter(reply("nope"), reply(output(span(turn_index=9))))
    with pytest.raises(ModelOutputInvalid, match="spans.0.turn_index"):
        analyze(adapter)
    assert len(adapter.requests) == 2


# --- Refusals and transport errors ---------------------------------------------------------------


def test_refusal_is_not_retried() -> None:
    adapter = FakeAdapter(reply("", stop_reason="refusal", refusal_category="cyber"))
    with pytest.raises(ModelRefused) as caught:
        analyze(adapter)
    assert caught.value.category == "cyber"
    assert len(adapter.requests) == 1


def test_refusal_on_the_retry_raises_refused() -> None:
    adapter = FakeAdapter(reply("nope"), reply("", stop_reason="refusal"))
    with pytest.raises(ModelRefused):
        analyze(adapter)


def test_transport_errors_propagate() -> None:
    adapter = FakeAdapter(ModelUnavailable("rate limited"))
    with pytest.raises(ModelUnavailable):
        analyze(adapter)


# --- Quote check ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quote",
    [
        "Sure, I will do it this afternoon.",  # paraphrased
        REQUEST_TEXT,  # real text, but from another turn
        "sure, i'll do it this afternoon.",  # different capitalisation
    ],
)
def test_quotes_not_in_their_turn_are_dropped_without_retry(quote: str) -> None:
    adapter = FakeAdapter(reply(output(request_span(), span(quote=quote))))
    result = analyze(adapter)
    assert [s.label for s in result.spans] == [Label.REQUEST]
    assert result.metadata.dropped_quotes == 1
    assert result.metadata.attempts == 1


def test_dropped_quote_is_logged_without_its_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    quote = "I will do it this afternoon."
    analyze(FakeAdapter(reply(output(request_span(), span(quote=quote)))))
    messages = [r.getMessage() for r in caplog.records]
    assert any("hallucinated_quote" in m and "turn=1" in m for m in messages)
    assert all(quote not in m for m in messages)


def test_no_log_line_contains_transcript_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    adapter = FakeAdapter(
        reply(output(span(label="CONDITIONAL"))),  # invalid: retried
        reply(output(request_span(), span(quote="I'll do it this afternoon, promise."))),
    )
    analyze(adapter)
    assert caplog.records, "the retry and the dropped quote should both be logged"
    for record in caplog.records:
        message = record.getMessage()
        assert REQUEST_TEXT not in message
        assert "this afternoon" not in message
