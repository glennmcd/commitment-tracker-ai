"""Pairing predicted spans with expected spans before scoring."""

import pytest

from commitment_tracker.evaluation.matching import Pair, match, overlap
from commitment_tracker.schemas import Label
from tests.eval.builders import exp, item, pred

SENTENCE = "I'll send the recap, and Priya will set up the pilot account."


def labels(pairs: list[Pair]) -> list[tuple[Label, Label]]:
    return [(p.expected_label, p.predicted_label) for p in pairs]


def test_overlap_is_the_share_of_the_shorter_quote() -> None:
    assert overlap("I'll send the recap", SENTENCE) == 1.0
    assert overlap("the pilot account", "I'll send the recap") == pytest.approx(1 / 3)  # "the"
    assert overlap("", SENTENCE) == 0.0


def test_exact_quote_matches() -> None:
    it = item("a", ["I'll send it Friday."], [exp(0, "COMMITMENT", "I'll send it Friday.")])
    pairs = match(it, [pred(0, "COMMITMENT", "I'll send it Friday.")])
    assert labels(pairs) == [(Label.COMMITMENT, Label.COMMITMENT)]
    assert pairs[0].expected is not None and pairs[0].predicted is not None


def test_partial_quote_matches() -> None:
    it = item("a", [SENTENCE], [exp(0, "COMMITMENT", "I'll send the recap")])
    assert labels(match(it, [pred(0, "HEDGED", "I'll send the recap,")])) == [
        (Label.COMMITMENT, Label.HEDGED)
    ]


def test_two_spans_in_one_turn_match_one_to_one() -> None:
    it = item(
        "a",
        [SENTENCE],
        [
            exp(0, "COMMITMENT", "I'll send the recap"),
            exp(0, "COMMITMENT", "Priya will set up the pilot account", owner="Priya"),
        ],
    )
    pairs = match(
        it,
        [
            pred(0, "COMMITMENT", "Priya will set up the pilot account", owner="Priya"),
            pred(0, "COMMITMENT", "I'll send the recap"),
        ],
    )
    assert len(pairs) == 2
    for pair in pairs:
        assert pair.expected is not None and pair.predicted is not None
        assert pair.expected.owner == pair.predicted.owner


def test_spans_in_different_turns_never_match() -> None:
    it = item(
        "a", ["Can you send it?", "Can you send it?"], [exp(1, "REQUEST", "Can you send it?")]
    )
    pairs = match(it, [pred(0, "REQUEST", "Can you send it?", owner=None)])
    assert labels(pairs) == [(Label.REQUEST, Label.NONE), (Label.NONE, Label.REQUEST)]


def test_a_missed_span_counts_as_predicted_none() -> None:
    it = item("a", ["I'll send it Friday."], [exp(0, "COMMITMENT", "I'll send it Friday.")])
    (pair,) = match(it, [])
    assert pair.predicted is None
    assert (pair.expected_label, pair.predicted_label) == (Label.COMMITMENT, Label.NONE)


def test_an_extra_non_none_span_is_a_false_positive() -> None:
    it = item("a", ["Our SLA is four hours."], [exp(0, "NONE", "Our SLA is four hours.")])
    pairs = match(
        it,
        [
            pred(0, "NONE", "Our SLA is four hours.", owner=None),
            pred(0, "COMMITMENT", "four hours"),
        ],
    )
    assert sorted(labels(pairs)) == sorted(
        [(Label.NONE, Label.NONE), (Label.NONE, Label.COMMITMENT)]
    )


def test_extra_none_spans_are_ignored() -> None:
    it = item("a", ["Hi. I'll send it."], [exp(0, "COMMITMENT", "I'll send it.")])
    pairs = match(it, [pred(0, "COMMITMENT", "I'll send it."), pred(0, "NONE", "Hi.", owner=None)])
    assert labels(pairs) == [(Label.COMMITMENT, Label.COMMITMENT)]


def test_weak_overlap_does_not_match() -> None:
    it = item("a", [SENTENCE], [exp(0, "COMMITMENT", "Priya will set up the pilot account")])
    pairs = match(it, [pred(0, "COMMITMENT", "I'll send the recap")])
    assert labels(pairs) == [(Label.COMMITMENT, Label.NONE), (Label.NONE, Label.COMMITMENT)]
