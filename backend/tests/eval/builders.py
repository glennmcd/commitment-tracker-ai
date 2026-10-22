"""Small builders for evaluation tests: items, expected spans and predicted spans."""

from datetime import date
from typing import Any

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.schemas import AnalyzeResponse, Metadata, Span


def item(
    item_id: str, texts: list[str], expected: list[dict[str, Any]], tags: list[str] | None = None
) -> EvalItem:
    return EvalItem.model_validate(
        {
            "id": item_id,
            "call_date": "2026-10-21",
            "turns": [{"speaker": "seller", "text": text} for text in texts],
            "tags": tags or [],
            "expected": expected,
        }
    )


def exp(turn: int, label: str, quote: str, **fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"turn_index": turn, "label": label, "quote": quote}
    if label in {"COMMITMENT", "HEDGED", "CONDITIONAL"}:
        data.setdefault("owner", "seller")
    if label == "CONDITIONAL":
        data.setdefault("condition", "it is approved")
    data.update(fields)
    return data


def pred(
    turn: int,
    label: str,
    quote: str,
    *,
    owner: str | None = "seller",
    action: str | None = None,
    resolved: date | None = None,
) -> Span:
    due: dict[str, Any] = {"raw": None, "resolved": None, "precision": "none"}
    if resolved is not None:
        due = {"raw": "by then", "resolved": resolved.isoformat(), "precision": "day"}
    return Span.model_validate(
        {
            "turn_index": turn,
            "label": label,
            "owner": owner,
            "recipient": None,
            "action": action,
            "due": due,
            "condition": "it is approved" if label == "CONDITIONAL" else None,
            "confidence": 0.9,
            "quote": quote,
            "rationale": "test",
            "ambiguous": False,
        }
    )


def response(
    *spans: Span,
    latency_ms: int = 1_000,
    cost_usd: float | None = 0.01,
    dropped_quotes: int = 0,
    attempts: int = 1,
    model: str = "claude-opus-5-5",
) -> AnalyzeResponse:
    return AnalyzeResponse(
        spans=list(spans),
        metadata=Metadata(
            model=model,
            served_by=model,
            prompt_version="v1",
            latency_ms=latency_ms,
            input_tokens=200,
            output_tokens=500,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=2_500,
            cost_usd=cost_usd,
            attempts=attempts,
            dropped_quotes=dropped_quotes,
        ),
    )
