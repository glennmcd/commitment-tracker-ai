"""Scores from item results: label metrics, ledger F1, field accuracy and run statistics."""

from datetime import date

import pytest

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.metrics import compute_scores, percentile
from commitment_tracker.evaluation.results import ItemResult
from tests.eval.builders import exp, item, pred, response

FRI = date(2026, 10, 23)
COMMIT = item(
    "c",
    ["I'll send the pricing by Friday."],
    [
        exp(
            0,
            "COMMITMENT",
            "I'll send the pricing by Friday.",
            action_keywords=["send", "pricing"],
            due_resolved="2026-10-23",
            precision="day",
        )
    ],
)
POLICY = item("n", ["Our SLA is four hours."], [exp(0, "NONE", "Our SLA is four hours.")])
SARCASM = item(
    "s",
    ["Sure, I'll rewrite it all by Friday."],
    [exp(0, "NONE", "Sure, I'll rewrite it all by Friday.")],
    tags=["ambiguous"],
)


def good_commit() -> ItemResult:
    span = pred(
        0, "COMMITMENT", "I'll send the pricing by Friday.", action="send the pricing", resolved=FRI
    )
    return ItemResult(COMMIT, response(span), error=None, cached=False)


def none_result(it: EvalItem = POLICY, label: str = "NONE") -> ItemResult:
    """The item's single turn predicted as `label` (NONE by default)."""
    owner = None if label == "NONE" else "seller"
    span = pred(0, label, it.turns[0].text, owner=owner)
    return ItemResult(it, response(span), error=None, cached=False)


def test_perfect_run() -> None:
    scores = compute_scores([good_commit(), none_result()])
    assert scores.accuracy == 1.0
    assert scores.ledger.f1 == 1.0
    assert scores.labels["COMMITMENT"].f1 == 1.0
    assert scores.labels["COMMITMENT"].support == 1
    assert scores.fields["owner"].accuracy == 1.0
    assert scores.fields["action"].accuracy == 1.0
    assert scores.fields["due"].accuracy == 1.0
    assert scores.confusion.labels[0] == "COMMITMENT"
    assert scores.confusion.rows[0][0] == 1  # COMMITMENT predicted as COMMITMENT
    assert scores.confusion.rows[7][7] == 1  # NONE predicted as NONE


def test_hedged_for_commitment_is_a_label_error_but_a_ledger_hit() -> None:
    hedged = pred(0, "HEDGED", "I'll send the pricing by Friday.", action="send pricing")
    scores = compute_scores([ItemResult(COMMIT, response(hedged), None, False), none_result()])
    assert scores.accuracy == 0.5
    assert scores.ledger.true_positives == 1
    assert scores.ledger.f1 == 1.0
    assert scores.confusion.rows[0][1] == 1  # COMMITMENT row, HEDGED column


def test_missed_commitment_and_false_positive() -> None:
    missed = ItemResult(COMMIT, response(), None, False)
    false_alarm = none_result(POLICY, "COMMITMENT")
    scores = compute_scores([missed, false_alarm])
    assert (scores.ledger.true_positives, scores.ledger.false_positives) == (0, 1)
    assert scores.ledger.false_negatives == 1
    assert scores.ledger.precision == 0.0
    assert scores.ledger.recall == 0.0
    assert scores.ledger.f1 == 0.0


def test_field_accuracy_counts_each_field() -> None:
    wrong = pred(
        0,
        "COMMITMENT",
        "I'll send the pricing by Friday.",
        owner="buyer",
        action="send the deck",
        resolved=date(2026, 10, 30),
    )
    scores = compute_scores([ItemResult(COMMIT, response(wrong), None, False), good_commit()])
    for field in ("owner", "action", "due"):
        assert (scores.fields[field].correct, scores.fields[field].total) == (1, 2), field
        assert scores.fields[field].accuracy == 0.5


def test_items_without_action_keywords_are_not_scored_for_action() -> None:
    vague = item("v", ["We'll circle back."], [exp(0, "HEDGED", "We'll circle back.")])
    result = ItemResult(vague, response(pred(0, "HEDGED", "We'll circle back.")), None, False)
    scores = compute_scores([result])
    assert scores.fields["action"].total == 0
    assert scores.fields["action"].accuracy is None
    assert scores.fields["owner"].total == 1


def test_ambiguous_items_are_reported_apart_from_the_headline() -> None:
    sarcastic_commit = none_result(SARCASM, "COMMITMENT")
    scores = compute_scores([good_commit(), none_result(), sarcastic_commit])
    assert scores.ledger.false_positives == 0  # the ambiguous item doesn't count
    assert scores.scored_items == 2
    (row,) = scores.ambiguous
    assert (row.item_id, row.expected, row.predicted) == ("s", "NONE", "COMMITMENT")


def test_failed_items_count_as_all_none_and_are_listed() -> None:
    failed = ItemResult(COMMIT, None, error="model_output_invalid", cached=False)
    scores = compute_scores([failed, none_result()])
    assert scores.ledger.false_negatives == 1
    assert [(f.item_id, f.error) for f in scores.failed_items] == [("c", "model_output_invalid")]


def test_run_statistics() -> None:
    slow = ItemResult(
        COMMIT,
        response(
            pred(0, "COMMITMENT", "I'll send the pricing by Friday."),
            latency_ms=4_000,
            cost_usd=0.03,
            dropped_quotes=2,
            attempts=2,
        ),
        None,
        cached=True,
    )
    scores = compute_scores([slow, none_result()])
    assert scores.quote_failures == 2
    assert scores.retried_items == 1
    assert scores.cache_hits == 1
    assert scores.latency_ms is not None
    assert (scores.latency_ms.p50, scores.latency_ms.p95) == (1_000, 4_000)
    assert scores.cost_usd == pytest.approx(0.04)


def test_cost_is_null_when_any_price_is_unknown() -> None:
    unknown = ItemResult(
        POLICY,
        response(pred(0, "NONE", "Our SLA is four hours.", owner=None), cost_usd=None),
        None,
        False,
    )
    assert compute_scores([good_commit(), unknown]).cost_usd is None


def test_no_successful_items_has_no_latency() -> None:
    scores = compute_scores([ItemResult(COMMIT, None, "model_unavailable", False)])
    assert scores.latency_ms is None


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [
        ([5], 50, 5),
        ([1, 2, 3, 4], 50, 2),
        ([1, 2, 3, 4], 95, 4),
        (list(range(1, 101)), 95, 95),
        ([10, 1, 7], 50, 7),
    ],
)
def test_nearest_rank_percentile(values: list[int], p: int, expected: int) -> None:
    assert percentile(values, p) == expected
