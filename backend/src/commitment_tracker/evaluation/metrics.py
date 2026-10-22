"""Scores for an evaluation run.

Headline numbers use every item not tagged ambiguous; ambiguous items are listed on their own. A
failed item counts as if the extractor returned nothing (every expected span predicted NONE) and is
listed with its error. Label metrics come from scikit-learn; ledger F1 treats COMMITMENT, HEDGED and
CONDITIONAL as positive. Field accuracy covers pairs where both sides are ledger labels.
"""

import math

from pydantic import BaseModel
from sklearn.metrics import classification_report, confusion_matrix

from commitment_tracker.evaluation.matching import Pair, match
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.schemas import LEDGER_LABELS, Label

LABELS = [label.value for label in Label]


class LabelScore(BaseModel):
    precision: float
    recall: float
    f1: float
    support: int


class LedgerScore(BaseModel):
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int


class FieldScore(BaseModel):
    correct: int
    total: int
    accuracy: float | None


class Confusion(BaseModel):
    labels: list[str]  # row = expected, column = predicted
    rows: list[list[int]]


class AmbiguousRow(BaseModel):
    item_id: str
    expected: str
    predicted: str


class FailedItem(BaseModel):
    item_id: str
    error: str


class Latency(BaseModel):
    p50: int
    p95: int


class Scores(BaseModel):
    items: int
    scored_items: int
    accuracy: float
    macro_f1: float
    labels: dict[str, LabelScore]
    confusion: Confusion
    ledger: LedgerScore
    fields: dict[str, FieldScore]
    ambiguous: list[AmbiguousRow]
    failed_items: list[FailedItem]
    quote_failures: int
    retried_items: int
    cache_hits: int
    latency_ms: Latency | None
    cost_usd: float | None


def percentile(values: list[int], p: float) -> int:
    """Nearest-rank percentile: the smallest value with at least p% of values at or below it."""
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _pairs(result: ItemResult) -> list[Pair]:
    return match(result.item, result.response.spans if result.response else [])


def _ledger(pairs: list[Pair]) -> LedgerScore:
    tp = sum(
        p.expected_label in LEDGER_LABELS and p.predicted_label in LEDGER_LABELS for p in pairs
    )
    fp = sum(
        p.expected_label not in LEDGER_LABELS and p.predicted_label in LEDGER_LABELS for p in pairs
    )
    fn = sum(
        p.expected_label in LEDGER_LABELS and p.predicted_label not in LEDGER_LABELS for p in pairs
    )
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    f1 = _ratio(2 * tp, 2 * tp + fp + fn)
    return LedgerScore(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
    )


def _fields(pairs: list[Pair]) -> dict[str, FieldScore]:
    counts = {"owner": [0, 0], "action": [0, 0], "due": [0, 0]}
    for pair in pairs:
        expected, predicted = pair.expected, pair.predicted
        if expected is None or predicted is None:
            continue
        if expected.label not in LEDGER_LABELS or predicted.label not in LEDGER_LABELS:
            continue
        checks = {
            "owner": (expected.owner or "").casefold() == (predicted.owner or "").casefold(),
            "due": expected.due_resolved == predicted.due.resolved,
        }
        if expected.action_keywords:
            action = (predicted.action or "").lower()
            checks["action"] = all(keyword in action for keyword in expected.action_keywords)
        for field, correct in checks.items():
            counts[field][0] += int(correct)
            counts[field][1] += 1
    return {
        field: FieldScore(correct=correct, total=total, accuracy=correct / total if total else None)
        for field, (correct, total) in counts.items()
    }


def _labels(pairs: list[Pair]) -> tuple[dict[str, LabelScore], Confusion, float, float]:
    y_true = [p.expected_label.value for p in pairs]
    y_pred = [p.predicted_label.value for p in pairs]
    if not pairs:
        empty = LabelScore(precision=0.0, recall=0.0, f1=0.0, support=0)
        zeros = [[0] * len(LABELS) for _ in LABELS]
        return {label: empty for label in LABELS}, Confusion(labels=LABELS, rows=zeros), 0.0, 0.0
    report = classification_report(y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0)
    labels = {
        label: LabelScore(
            precision=report[label]["precision"],
            recall=report[label]["recall"],
            f1=report[label]["f1-score"],
            support=int(report[label]["support"]),
        )
        for label in LABELS
    }
    matrix = confusion_matrix(y_true, y_pred, labels=LABELS).tolist()
    accuracy = sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / len(pairs)
    return labels, Confusion(labels=LABELS, rows=matrix), accuracy, report["macro avg"]["f1-score"]


def compute_scores(results: list[ItemResult]) -> Scores:
    headline: list[Pair] = []
    ambiguous: list[AmbiguousRow] = []
    for result in results:
        pairs = _pairs(result)
        if "ambiguous" in result.item.tags:
            ambiguous += [
                AmbiguousRow(
                    item_id=result.item.id,
                    expected=p.expected_label.value,
                    predicted=p.predicted_label.value,
                )
                for p in pairs
            ]
        else:
            headline += pairs

    labels, confusion, accuracy, macro_f1 = _labels(headline)
    responses = [r.response for r in results if r.response is not None]
    costs = [r.metadata.cost_usd for r in responses]
    latencies = [r.metadata.latency_ms for r in responses]
    return Scores(
        items=len(results),
        scored_items=sum("ambiguous" not in r.item.tags for r in results),
        accuracy=accuracy,
        macro_f1=macro_f1,
        labels=labels,
        confusion=confusion,
        ledger=_ledger(headline),
        fields=_fields(headline),
        ambiguous=ambiguous,
        failed_items=[
            FailedItem(item_id=r.item.id, error=r.error) for r in results if r.error is not None
        ],
        quote_failures=sum(r.metadata.dropped_quotes for r in responses),
        retried_items=sum(r.metadata.attempts > 1 for r in responses),
        cache_hits=sum(r.cached for r in results),
        latency_ms=(
            Latency(p50=percentile(latencies, 50), p95=percentile(latencies, 95))
            if latencies
            else None
        ),
        cost_usd=None if None in costs else sum(c for c in costs if c is not None),
    )
