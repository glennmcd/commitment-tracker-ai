"""Re-score committed reports from their stored predictions, offline.

A report keeps each item's predicted spans, so after a change to matching or metrics its scores can
be rebuilt against the current set items without calling a model. Only the scores change; the run
record and per-item details stay as written. The regression gate uses the same function to check
that committed scores are not stale.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.metrics import compute_scores
from commitment_tracker.evaluation.report import (
    ItemDetail,
    PredictedSpan,
    Report,
    RunInfo,
    scores_by_provenance,
    write_report,
)
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.evaluation.sets import load_set
from commitment_tracker.schemas import AnalyzeResponse, Due, Metadata, Span


class RescoreError(ValueError):
    pass


@dataclass(frozen=True)
class RescoreOutcome:
    path: Path
    status: Literal["updated", "unchanged", "skipped"]
    reason: str = ""


def _span(stored: PredictedSpan) -> Span:
    return Span(
        turn_index=stored.turn_index,
        label=stored.label,
        owner=stored.owner,
        recipient=stored.recipient,
        action=stored.action,
        due=Due(raw=stored.due_raw, resolved=stored.due_resolved, precision=stored.precision),
        condition=stored.condition,
        confidence=0.0,  # not stored: scoring never reads it
        quote=stored.quote,
        rationale="",
        ambiguous=False,
    )


def _result(detail: ItemDetail, item: EvalItem, run: RunInfo) -> ItemResult:
    if detail.spans is None:
        raise RescoreError(f"{detail.item_id} was written before predictions were stored")
    if detail.error is not None:
        return ItemResult(item, None, error=detail.error, cached=detail.cached)
    metadata = Metadata(
        model=run.model,
        served_by=detail.served_by or run.model,
        prompt_version=run.prompt_version,
        latency_ms=detail.latency_ms or 0,
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        cost_usd=detail.cost_usd,
        attempts=detail.attempts or 1,
        dropped_quotes=detail.dropped_quotes or 0,
    )
    response = AnalyzeResponse(spans=[_span(s) for s in detail.spans], metadata=metadata)
    return ItemResult(item, response, error=None, cached=detail.cached)


def rescore(report: Report, items: dict[str, EvalItem]) -> Report:
    """The report with its scores rebuilt from its stored spans and the given items."""
    missing = [d.item_id for d in report.items if d.item_id not in items]
    if missing:
        raise RescoreError(f"items not in the set: {', '.join(missing)}")
    results = [_result(d, items[d.item_id], report.run) for d in report.items]
    return report.model_copy(
        update={"scores": compute_scores(results), "by_provenance": scores_by_provenance(results)}
    )


def rescore_set(set_name: str, root: Path, reports_dir: Path) -> list[RescoreOutcome]:
    """Re-score every report of the set's current version under reports_dir/<set>/."""
    loaded = load_set(set_name, root)
    items = {item.id: item for item in loaded.items}
    directory = reports_dir / set_name
    outcomes = []
    for path in sorted(directory.glob("*.json")):
        report = Report.model_validate_json(path.read_text(encoding="utf-8"))
        if report.run.set_sha256 is None:
            outcomes.append(RescoreOutcome(path, "skipped", "written before named sets"))
            continue
        if report.run.set_sha256 != loaded.sha256:
            outcomes.append(RescoreOutcome(path, "skipped", "the set changed since this run"))
            continue
        try:
            rescored = rescore(report, items)
        except RescoreError as error:
            outcomes.append(RescoreOutcome(path, "skipped", str(error)))
            continue
        if rescored == report:
            outcomes.append(RescoreOutcome(path, "unchanged"))
            continue
        write_report(rescored, directory)
        outcomes.append(RescoreOutcome(path, "updated"))
    return outcomes
