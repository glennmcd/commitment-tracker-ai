"""Pairs predicted spans with expected spans so each can be scored.

Spans pair only within the same turn, by word overlap of their quotes (the share of the shorter
quote's words found in the other), one-to-one, best overlap first. An expected span with no partner
counts as predicted NONE (a miss); a predicted non-NONE span with no partner counts against expected
NONE (a false positive). Unpaired predicted NONE spans are ignored: the model labels every turn, and
extra NONE spans change nothing in the ledger.
"""

import re
from dataclasses import dataclass

from commitment_tracker.evaluation.dataset import EvalItem, ExpectedSpan
from commitment_tracker.schemas import Label, Span

MIN_OVERLAP = 0.6
WORD = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class Pair:
    expected: ExpectedSpan | None
    predicted: Span | None

    @property
    def expected_label(self) -> Label:
        return self.expected.label if self.expected else Label.NONE

    @property
    def predicted_label(self) -> Label:
        return self.predicted.label if self.predicted else Label.NONE


def overlap(a: str, b: str) -> float:
    words_a, words_b = set(WORD.findall(a.lower())), set(WORD.findall(b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def match(item: EvalItem, predicted: list[Span]) -> list[Pair]:
    candidates = sorted(
        (
            (-overlap(exp.quote, pred.quote), e, p)
            for e, exp in enumerate(item.expected)
            for p, pred in enumerate(predicted)
            if exp.turn_index == pred.turn_index
        ),
    )
    partner: dict[int, int] = {}
    taken: set[int] = set()
    for negative_score, e, p in candidates:
        if -negative_score < MIN_OVERLAP:
            break
        if e not in partner and p not in taken:
            partner[e] = p
            taken.add(p)

    pairs = [
        Pair(exp, predicted[partner[e]] if e in partner else None)
        for e, exp in enumerate(item.expected)
    ]
    pairs += [
        Pair(None, pred)
        for p, pred in enumerate(predicted)
        if p not in taken and pred.label is not Label.NONE
    ]
    return pairs
