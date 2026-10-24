"""The evaluation dataset: the dev set matches the spec's 24 seed utterances, and the loader rejects
malformed items with the line number."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation.dataset import (
    DEV_PATH,
    DatasetError,
    EvalItem,
    load_dataset,
)
from commitment_tracker.extractor.dates import resolve_due
from commitment_tracker.schemas import LEDGER_LABELS, Label, Precision

CALL_DATE = date(2026, 10, 21)


@pytest.fixture(scope="module")
def dev() -> dict[str, EvalItem]:
    return {item.id: item for item in load_dataset(DEV_PATH)}


# --- The dev set ---------------------------------------------------------------------------------


def test_dev_set_has_the_24_spec_items_in_order(dev: dict[str, EvalItem]) -> None:
    assert list(dev) == [f"spec-{n:02d}" for n in range(1, 25)]
    assert all(item.call_date == CALL_DATE for item in dev.values())


def test_spec_items_are_accepted_with_spec_provenance(dev: dict[str, EvalItem]) -> None:
    spec = [item for item in dev.values() if item.id.startswith("spec-")]
    assert {(item.provenance, item.review) for item in spec} == {("spec", "accepted")}


@pytest.mark.parametrize("provenance", ["spec", "hand-written", "gemini-3-pro", "gpt-5.2"])
def test_provenance_values(provenance: str) -> None:
    assert EvalItem.model_validate(item_data(provenance=provenance)).provenance == provenance


def test_dev_set_covers_every_label(dev: dict[str, EvalItem]) -> None:
    labels = {span.label for item in dev.values() for span in item.expected}
    assert labels == set(Label)


@pytest.mark.parametrize(
    ("item_id", "label"),
    [
        ("spec-01", Label.COMMITMENT),
        ("spec-04", Label.COMMITMENT),
        ("spec-07", Label.HEDGED),
        ("spec-10", Label.HEDGED),
        ("spec-11", Label.CONDITIONAL),
        ("spec-13", Label.SUGGESTION),
        ("spec-15", Label.REQUEST),
        ("spec-17", Label.REPORTED),
        ("spec-18", Label.REPORTED),
        ("spec-19", Label.REFUSAL),
        ("spec-20", Label.REFUSAL),
        ("spec-21", Label.NONE),
        ("spec-23", Label.NONE),
        ("spec-24", Label.NONE),
    ],
)
def test_labels_match_the_spec_table(dev: dict[str, EvalItem], item_id: str, label: Label) -> None:
    assert [span.label for span in dev[item_id].expected] == [label]


@pytest.mark.parametrize(
    ("item_id", "resolved", "precision"),
    [
        ("spec-01", date(2026, 10, 23), Precision.DAY),
        ("spec-02", date(2026, 10, 30), Precision.DAY),
        ("spec-03", date(2026, 10, 22), Precision.DAY),
        ("spec-04", None, Precision.EVENT),
        ("spec-07", date(2026, 10, 19), Precision.WEEK),
        ("spec-08", date(2026, 10, 26), Precision.DAY),
        ("spec-09", None, Precision.VAGUE),
        ("spec-10", None, Precision.NONE),
        ("spec-11", date(2026, 11, 1), Precision.DAY),
        ("spec-12", date(2026, 10, 27), Precision.DAY),
    ],
)
def test_due_dates_match_the_spec_table(
    dev: dict[str, EvalItem], item_id: str, resolved: date | None, precision: Precision
) -> None:
    (span,) = dev[item_id].expected
    assert (span.due_resolved, span.precision) == (resolved, precision)


def test_request_and_reply_item(dev: dict[str, EvalItem]) -> None:
    item = dev["spec-05"]
    assert [turn.speaker for turn in item.turns] == ["buyer", "seller"]
    request, reply = item.expected
    assert (request.turn_index, request.label) == (0, Label.REQUEST)
    assert (reply.turn_index, reply.label, reply.owner) == (1, Label.COMMITMENT, "seller")
    assert reply.recipient == "buyer"
    assert reply.due_resolved == CALL_DATE
    assert "multi_turn" in item.tags


def test_two_commitments_with_a_named_owner(dev: dict[str, EvalItem]) -> None:
    first, second = dev["spec-06"].expected
    assert (first.owner, second.owner) == ("seller", "Priya")
    assert first.label == second.label == Label.COMMITMENT


def test_conditions_are_recorded(dev: dict[str, EvalItem]) -> None:
    assert dev["spec-11"].expected[0].condition == "legal signs off"
    assert dev["spec-12"].expected[0].condition == "procurement approves the PO"


@pytest.mark.parametrize("item_id", ["spec-22", "spec-24"])
def test_ambiguous_items_are_tagged(dev: dict[str, EvalItem], item_id: str) -> None:
    assert "ambiguous" in dev[item_id].tags


def test_ledger_items_carry_scored_fields(dev: dict[str, EvalItem]) -> None:
    for item in dev.values():
        for span in item.expected:
            if span.label in LEDGER_LABELS:
                assert span.owner, item.id
                assert span.action_keywords or item.id in {"spec-07", "spec-10"}, item.id


def test_expected_dates_agree_with_the_resolver(dev: dict[str, EvalItem]) -> None:
    # The dataset and the resolver must not drift apart: the raw phrase resolves to the expectation.
    for item in dev.values():
        for span in item.expected:
            if span.due_raw is not None and span.precision in {Precision.DAY, Precision.WEEK}:
                resolved = resolve_due(span.due_raw, item.call_date)
                assert (resolved.resolved, resolved.precision) == (
                    span.due_resolved,
                    span.precision,
                ), item.id


# --- The loader ----------------------------------------------------------------------------------


def item_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "x-01",
        "call_date": "2026-10-21",
        "turns": [{"speaker": "seller", "text": "I'll send it Friday."}],
        "tags": [],
        "expected": [
            {
                "turn_index": 0,
                "label": "COMMITMENT",
                "quote": "I'll send it Friday.",
                "owner": "seller",
                "action_keywords": ["send"],
                "due_raw": "Friday",
                "due_resolved": "2026-10-23",
                "precision": "day",
            }
        ],
        "provenance": "hand-written",
        "review": "accepted",
    }
    data.update(overrides)
    return data


def write_lines(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "set.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_loads_items_and_skips_blank_lines(tmp_path: Path) -> None:
    path = write_lines(tmp_path, json.dumps(item_data()), "", json.dumps(item_data(id="x-02")))
    assert [item.id for item in load_dataset(path)] == ["x-01", "x-02"]


def expected(**overrides: Any) -> list[dict[str, Any]]:
    return [{**item_data()["expected"][0], **overrides}]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (item_data(expected=expected(quote="I will send it")), "quote is not in turn 0"),
        (item_data(expected=expected(turn_index=3)), "turn_index 3"),
        (item_data(expected=expected(label="CONDITIONAL")), "condition"),
        (item_data(expected=expected(owner=None)), "owner"),
        (item_data(expected=expected(precision="vague")), "day or week"),
        (item_data(expected=expected(action_keywords=["Send"])), "lower case"),
        (item_data(tags=["spicy"]), "tags"),
        (item_data(expected=[]), "at least 1"),
        (item_data(surprise=True), "Extra inputs"),
        (item_data(call_date="21/10/2026"), "date"),
        (item_data(provenance="Gemini 3"), "provenance"),
        (item_data(review="maybe"), "review"),
        ({k: v for k, v in item_data().items() if k != "provenance"}, "provenance"),
    ],
)
def test_invalid_item_is_rejected_with_its_line(
    tmp_path: Path, data: dict[str, Any], message: str
) -> None:
    path = write_lines(tmp_path, json.dumps(item_data(id="ok")), json.dumps(data))
    with pytest.raises(DatasetError, match=rf"line 2.*{message}"):
        load_dataset(path)


def test_bad_json_is_rejected_with_its_line(tmp_path: Path) -> None:
    path = write_lines(tmp_path, json.dumps(item_data()), "{not json")
    with pytest.raises(DatasetError, match="line 2"):
        load_dataset(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = write_lines(tmp_path, json.dumps(item_data()), json.dumps(item_data()))
    with pytest.raises(DatasetError, match="line 2.*duplicate id x-01"):
        load_dataset(path)


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="no items"):
        load_dataset(write_lines(tmp_path, ""))
