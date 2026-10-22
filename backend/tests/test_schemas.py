"""The shared contract: what the API accepts and returns, and what a validated span must satisfy."""

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from commitment_tracker.schemas import (
    LEDGER_LABELS,
    MAX_TRANSCRIPT_CHARS,
    MAX_TURNS,
    AnalyzeRequest,
    AnalyzeResponse,
    Due,
    Label,
    Metadata,
    Precision,
    Span,
)

# --- Span ----------------------------------------------------------------------------------------


def span_data(**overrides: Any) -> dict[str, Any]:
    """The spec's example span, as the API would return it."""
    data: dict[str, Any] = {
        "turn_index": 0,
        "label": "COMMITMENT",
        "owner": "speaker_1",
        "recipient": "speaker_2",
        "action": "send revised pricing",
        "due": {"raw": "by Friday", "resolved": "2026-10-23", "precision": "day"},
        "condition": None,
        "confidence": 0.92,
        "quote": "I'll send you the revised pricing by Friday.",
        "rationale": "First-person future action with a specific deadline.",
        "ambiguous": False,
    }
    data.update(overrides)
    return data


def test_valid_span_parses() -> None:
    span = Span.model_validate(span_data())
    assert span.label is Label.COMMITMENT
    assert span.due.resolved == date(2026, 10, 23)
    assert span.due.precision is Precision.DAY


def test_conditional_span_with_condition_parses() -> None:
    span = Span.model_validate(span_data(label="CONDITIONAL", condition="legal signs off"))
    assert span.condition == "legal signs off"


@pytest.mark.parametrize(
    "label",
    ["SUGGESTION", "REQUEST", "REPORTED", "REFUSAL", "NONE"],
)
def test_non_ledger_spans_may_have_no_owner(label: str) -> None:
    span = Span.model_validate(span_data(label=label, owner=None, recipient=None, action=None))
    assert span.owner is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"confidence": 1.2}, "less than or equal to 1"),
        ({"confidence": -0.1}, "greater than or equal to 0"),
        ({"label": "PROMISE"}, "COMMITMENT"),
        ({"label": "commitment"}, "COMMITMENT"),
        ({"quote": ""}, "at least 1 character"),
        ({"turn_index": -1}, "greater than or equal to 0"),
        ({"label": "CONDITIONAL", "condition": None}, "condition is required"),
        ({"label": "CONDITIONAL", "condition": "  "}, "condition is required"),
        ({"label": "COMMITMENT", "owner": None}, "owner is required"),
        ({"label": "HEDGED", "owner": " "}, "owner is required"),
        ({"surprise": 1}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_span_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Span.model_validate(span_data(**overrides))


@pytest.mark.parametrize(
    ("label", "in_ledger", "soft"),
    [
        ("COMMITMENT", True, False),
        ("HEDGED", True, True),
        ("CONDITIONAL", True, False),
        ("SUGGESTION", False, False),
        ("REQUEST", False, False),
        ("REPORTED", False, False),
        ("REFUSAL", False, False),
        ("NONE", False, False),
    ],
)
def test_ledger_flags_follow_the_label(label: str, in_ledger: bool, soft: bool) -> None:
    overrides: dict[str, Any] = {"label": label}
    if label == "CONDITIONAL":
        overrides["condition"] = "legal signs off"
    span = Span.model_validate(span_data(**overrides))
    assert span.in_ledger is in_ledger
    assert span.soft is soft


def test_ledger_labels_are_the_first_three() -> None:
    assert {Label.COMMITMENT, Label.HEDGED, Label.CONDITIONAL} == LEDGER_LABELS


def test_span_serializes_ledger_flags_and_iso_date() -> None:
    dumped = Span.model_validate(span_data(label="HEDGED")).model_dump(mode="json")
    assert dumped["in_ledger"] is True
    assert dumped["soft"] is True
    assert dumped["due"]["resolved"] == "2026-10-23"


def test_span_round_trips_through_json() -> None:
    span = Span.model_validate(span_data())
    assert Span.model_validate_json(span.model_dump_json(exclude={"in_ledger", "soft"})) == span


# --- Due -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        {"raw": "by Friday", "resolved": "2026-10-23", "precision": "day"},
        {"raw": "this week", "resolved": "2026-10-19", "precision": "week"},
        {"raw": "before your board meeting", "resolved": None, "precision": "event"},
        {"raw": "soon", "resolved": None, "precision": "vague"},
        {"raw": "on Friday", "resolved": None, "precision": "day"},  # recognised kind, unresolved
        {"raw": None, "resolved": None, "precision": "none"},
    ],
)
def test_valid_due(data: dict[str, Any]) -> None:
    Due.model_validate(data)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"raw": "soon", "resolved": "2026-10-23", "precision": "vague"}, "only day or week"),
        ({"raw": "board meeting", "resolved": "2026-10-23", "precision": "event"}, "only day or"),
        ({"raw": "by Friday", "resolved": None, "precision": "none"}, "precision none"),
        ({"raw": None, "resolved": "2026-10-23", "precision": "day"}, "needs the raw phrase"),
        ({"raw": "", "resolved": None, "precision": "vague"}, "at least 1 character"),
        ({"raw": "Friday", "resolved": "23/10/2026", "precision": "day"}, "date"),
        ({"raw": "Friday", "resolved": None, "precision": "month"}, "day"),
    ],
)
def test_invalid_due(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Due.model_validate(data)


# --- AnalyzeRequest ------------------------------------------------------------------------------


def request_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "transcript": [
            {"speaker": "buyer", "text": "Can you resend the invoice?"},
            {"speaker": "seller", "text": "Sure, I'll do it this afternoon."},
        ],
        "call_date": "2026-10-21",
    }
    data.update(overrides)
    return data


def test_valid_request_parses() -> None:
    request = AnalyzeRequest.model_validate(request_data(timezone="America/New_York"))
    assert request.call_date == date(2026, 10, 21)
    assert request.transcript[1].speaker == "seller"
    assert request.timezone == "America/New_York"


def test_timezone_is_optional() -> None:
    assert AnalyzeRequest.model_validate(request_data()).timezone is None


def test_request_at_the_limits_parses() -> None:
    turns = [{"speaker": "a", "text": "x" * 100} for _ in range(MAX_TURNS)]
    assert MAX_TURNS * 100 == MAX_TRANSCRIPT_CHARS
    AnalyzeRequest.model_validate(request_data(transcript=turns))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"transcript": []}, "at least 1 item"),
        (
            {"transcript": [{"speaker": "a", "text": "hi"}] * (MAX_TURNS + 1)},
            f"at most {MAX_TURNS} items",
        ),
        (
            {"transcript": [{"speaker": "a", "text": "x" * (MAX_TRANSCRIPT_CHARS + 1)}]},
            f"at most {MAX_TRANSCRIPT_CHARS} characters",
        ),
        (
            {"transcript": [{"speaker": "a", "text": "x" * 10_001}] * 2},
            f"at most {MAX_TRANSCRIPT_CHARS} characters",
        ),
        ({"transcript": [{"speaker": "a", "text": "   "}]}, "must not be blank"),
        ({"transcript": [{"speaker": "", "text": "hi"}]}, "at least 1 character"),
        ({"call_date": "21/10/2026"}, "date"),
        ({"call_date": None}, "date"),
        ({"timezone": "x" * 65}, "at most 64 characters"),
        ({"extra": True}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_request_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AnalyzeRequest.model_validate(request_data(**overrides))


def test_turn_timestamps_are_optional() -> None:
    turn = AnalyzeRequest.model_validate(request_data()).transcript[0]
    assert turn.start_ms is None
    assert turn.end_ms is None


@pytest.mark.parametrize(
    ("start_ms", "end_ms"),
    [(0, 0), (0, 4_200), (1_500, 61_000), (None, 4_200), (1_500, None)],
)
def test_turn_timestamps_parse(start_ms: int | None, end_ms: int | None) -> None:
    turn = {"speaker": "seller", "text": "I'll send it.", "start_ms": start_ms, "end_ms": end_ms}
    parsed = AnalyzeRequest.model_validate(request_data(transcript=[turn])).transcript[0]
    assert (parsed.start_ms, parsed.end_ms) == (start_ms, end_ms)


@pytest.mark.parametrize(
    ("timestamps", "message"),
    [
        ({"start_ms": -1}, "greater than or equal to 0"),
        ({"end_ms": -1}, "greater than or equal to 0"),
        ({"start_ms": 4_200, "end_ms": 4_199}, "end_ms must not be before start_ms"),
        ({"start_ms": 1.5}, "valid integer"),
    ],
)
def test_invalid_turn_timestamps_are_rejected(timestamps: dict[str, Any], message: str) -> None:
    turn = {"speaker": "seller", "text": "I'll send it.", **timestamps}
    with pytest.raises(ValidationError, match=message):
        AnalyzeRequest.model_validate(request_data(transcript=[turn]))


SECRET = "pricing-is-42"


@pytest.mark.parametrize(
    "overrides",
    [
        {"transcript": [{"speaker": "a", "text": SECRET}] * (MAX_TURNS + 1)},
        {"transcript": [{"speaker": "a", "text": SECRET * 2_000}]},
        {"transcript": [{"speaker": SECRET * 10, "text": "hi"}]},
        {"transcript": [{"speaker": "a", "text": SECRET}], "call_date": "not a date"},
    ],
)
def test_request_errors_do_not_echo_input(overrides: dict[str, Any]) -> None:
    # Pydantic otherwise prints a truncated repr of the input (input_value=...), which can carry
    # transcript text into logs and error messages.
    with pytest.raises(ValidationError) as caught:
        AnalyzeRequest.model_validate(request_data(**overrides))
    assert "input_value" not in str(caught.value)
    assert SECRET not in str(caught.value)


def test_span_errors_do_not_echo_the_quote() -> None:
    with pytest.raises(ValidationError) as caught:
        Span.model_validate(span_data(quote=SECRET, confidence=2))
    assert "input_value" not in str(caught.value)
    assert SECRET not in str(caught.value)


# --- AnalyzeResponse -----------------------------------------------------------------------------


def metadata_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "model": "claude-opus-5-5",
        "served_by": "claude-opus-5-5",
        "prompt_version": "v1",
        "latency_ms": 2140,
        "input_tokens": 230,
        "output_tokens": 812,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 2510,
        "cost_usd": 0.0172,
        "attempts": 1,
        "dropped_quotes": 0,
    }
    data.update(overrides)
    return data


def test_response_parses_and_serializes() -> None:
    response = AnalyzeResponse.model_validate({"spans": [span_data()], "metadata": metadata_data()})
    dumped = response.model_dump(mode="json")
    assert dumped["spans"][0]["in_ledger"] is True
    assert dumped["metadata"]["served_by"] == "claude-opus-5-5"


def test_unknown_model_cost_is_null() -> None:
    assert Metadata.model_validate(metadata_data(cost_usd=None)).cost_usd is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"latency_ms": -1}, "greater than or equal to 0"),
        ({"output_tokens": -5}, "greater than or equal to 0"),
        ({"cost_usd": -0.01}, "greater than or equal to 0"),
        ({"attempts": 0}, "greater than or equal to 1"),
        ({"attempts": 3}, "less than or equal to 2"),
        ({"dropped_quotes": -1}, "greater than or equal to 0"),
    ],
)
def test_invalid_metadata_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Metadata.model_validate(metadata_data(**overrides))


def test_response_schema_lists_ledger_flags_as_required_outputs() -> None:
    schema = AnalyzeResponse.model_json_schema(mode="serialization")
    span = schema["$defs"]["Span"]
    assert {"in_ledger", "soft"} <= set(span["required"])
