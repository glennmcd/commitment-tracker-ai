"""What the model must return: the shape sent as the structured-output schema."""

from typing import Any

import pytest
from pydantic import ValidationError

from commitment_tracker.extractor.model_output import ModelOutput, ModelSpan
from commitment_tracker.schemas import Label, Precision


def model_span(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "turn_index": 1,
        "label": "COMMITMENT",
        "owner": "seller",
        "recipient": "buyer",
        "action": "resend the invoice",
        "due": {"raw": "this afternoon", "precision_hint": "day"},
        "condition": None,
        "confidence": 0.9,
        "quote": "Sure, I'll do it this afternoon.",
        "rationale": "The seller agrees to the buyer's request with a time.",
        "ambiguous": False,
    }
    data.update(overrides)
    return data


def test_valid_output_parses_from_json() -> None:
    output = ModelOutput.model_validate_json(
        '{"spans": [' + ModelSpan.model_validate(model_span()).model_dump_json() + "]}"
    )
    assert output.spans[0].label is Label.COMMITMENT
    assert output.spans[0].due.precision_hint is Precision.DAY


@pytest.mark.parametrize("label", ["commitment", "Commitment", " COMMITMENT "])
def test_label_casing_drift_is_accepted(label: str) -> None:
    # Structured outputs can change enum capitalisation without any error (docs, "Invalid outputs").
    assert ModelSpan.model_validate(model_span(label=label)).label is Label.COMMITMENT


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"label": "PROMISE"}, "COMMITMENT"),
        ({"confidence": 1.5}, "less than or equal to 1"),
        ({"turn_index": -1}, "greater than or equal to 0"),
        ({"due": {"raw": "Friday"}}, "precision_hint"),
        ({"due": {"raw": "Friday", "precision_hint": "month"}}, "day"),
        ({"surprise": 1}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_span_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ModelSpan.model_validate(model_span(**overrides))


def test_errors_do_not_echo_the_quote() -> None:
    # Validation errors go back to the model in the retry message and into logs.
    with pytest.raises(ValidationError) as caught:
        ModelSpan.model_validate(model_span(quote="pricing-is-42", confidence=7))
    assert "pricing-is-42" not in str(caught.value)
    assert "input_value" not in str(caught.value)


def test_every_field_is_required_in_the_schema() -> None:
    # Structured outputs limit optional parameters, so nullable fields are required instead.
    schema = ModelOutput.model_json_schema()
    span = schema["$defs"]["ModelSpan"]
    assert set(span["required"]) == set(span["properties"])
    due = schema["$defs"]["ModelDue"]
    assert set(due["required"]) == set(due["properties"])


def test_rationale_is_described_as_an_explanation_not_reasoning() -> None:
    # Asking for "reasoning" in an output field can trigger a reasoning_extraction refusal.
    description = ModelSpan.model_json_schema()["properties"]["rationale"]["description"]
    assert "explanation" in description
    assert "reason" not in description.lower()
