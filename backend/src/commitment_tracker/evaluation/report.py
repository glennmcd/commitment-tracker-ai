"""Evaluation reports: JSON for tools and comparisons, markdown for people.

Files go to backend/eval/reports/ as `<UTC start>-<model>-<prompt>.json` and `.md`.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from commitment_tracker.evaluation.metrics import Scores, compute_scores
from commitment_tracker.evaluation.results import ItemResult

# backend/src/commitment_tracker/evaluation/report.py -> backend/eval/reports
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[3] / "eval" / "reports"


class RunInfo(BaseModel):
    model: str
    prompt_version: str
    prompt_sha256: str
    effort: str
    dataset: str
    started_at: datetime
    duration_seconds: float
    served_by: list[str] = Field(default_factory=list)  # more than one after refusal fallbacks


class ItemDetail(BaseModel):
    item_id: str
    tags: list[str]
    expected: list[str]
    predicted: list[str]
    error: str | None
    cached: bool
    attempts: int | None
    dropped_quotes: int | None


class Report(BaseModel):
    run: RunInfo
    scores: Scores
    items: list[ItemDetail]


def build_report(run: RunInfo, results: list[ItemResult]) -> Report:
    served = sorted({r.response.metadata.served_by for r in results if r.response})
    details = [
        ItemDetail(
            item_id=r.item.id,
            tags=list(r.item.tags),
            expected=[span.label.value for span in r.item.expected],
            predicted=[span.label.value for span in r.response.spans] if r.response else [],
            error=r.error,
            cached=r.cached,
            attempts=r.response.metadata.attempts if r.response else None,
            dropped_quotes=r.response.metadata.dropped_quotes if r.response else None,
        )
        for r in results
    ]
    return Report(
        run=run.model_copy(update={"served_by": served}),
        scores=compute_scores(results),
        items=details,
    )


def _f(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def render_markdown(report: Report) -> str:
    run, scores = report.run, report.scores
    ledger = scores.ledger
    lines = [
        f"# Evaluation: {run.model}, prompt {run.prompt_version}",
        "",
        f"{run.started_at:%Y-%m-%d %H:%M} UTC · {run.dataset} · {scores.items} items "
        f"({scores.scored_items} scored, {len(scores.ambiguous)} ambiguous spans reported apart)",
        "",
        "## Headline",
        "",
        _row("Metric", "Value"),
        _row("---", "---"),
        _row("Ledger F1", _f(ledger.f1)),
        _row("Ledger precision", _f(ledger.precision)),
        _row("Ledger recall", _f(ledger.recall)),
        _row("Label accuracy", _f(scores.accuracy)),
        _row("Macro F1 (8 labels)", _f(scores.macro_f1)),
        _row("Failed items", len(scores.failed_items)),
        "",
        "## Labels",
        "",
        _row("Label", "Precision", "Recall", "F1", "Support"),
        _row("---", "---", "---", "---", "---"),
    ]
    lines += [
        _row(label, _f(s.precision), _f(s.recall), _f(s.f1), s.support)
        for label, s in scores.labels.items()
    ]
    lines += [
        "",
        "## Confusion matrix",
        "",
        "Rows are expected labels, columns predicted.",
        "",
        _row("", *scores.confusion.labels),
        _row("---", *(["---"] * len(scores.confusion.labels))),
    ]
    lines += [
        _row(label, *row)
        for label, row in zip(scores.confusion.labels, scores.confusion.rows, strict=True)
    ]
    lines += [
        "",
        "## Field accuracy",
        "",
        "Ledger spans whose expected and predicted labels are both ledger labels.",
        "",
        _row("Field", "Correct", "Total", "Accuracy"),
        _row("---", "---", "---", "---"),
    ]
    lines += [_row(field, s.correct, s.total, _f(s.accuracy)) for field, s in scores.fields.items()]
    lines += ["", "## Ambiguous items", ""]
    if scores.ambiguous:
        lines += [_row("Item", "Expected", "Predicted"), _row("---", "---", "---")]
        lines += [_row(a.item_id, a.expected, a.predicted) for a in scores.ambiguous]
    else:
        lines.append("None.")
    latency = scores.latency_ms
    lines += [
        "",
        "## Run",
        "",
        _row("Item", "Value"),
        _row("---", "---"),
        _row("Model requested", run.model),
        _row("Served by", ", ".join(run.served_by) or "n/a"),
        _row("Prompt", f"{run.prompt_version} (sha256 {run.prompt_sha256[:12]})"),
        _row("Effort", run.effort),
        _row("Latency p50 / p95", f"{latency.p50} / {latency.p95} ms" if latency else "n/a"),
        _row("Total cost", f"${scores.cost_usd:.4f}" if scores.cost_usd is not None else "n/a"),
        _row("Cache hits", scores.cache_hits),
        _row("Items retried", scores.retried_items),
        _row("Quote-check failures", scores.quote_failures),
        _row("Duration", f"{run.duration_seconds:.1f} s"),
    ]
    if scores.failed_items:
        lines += [
            "",
            "Failed: " + ", ".join(f"{f.item_id} ({f.error})" for f in scores.failed_items),
        ]
    lines += [
        "",
        "## Items",
        "",
        _row("Item", "Expected", "Predicted", "Tags", "Notes"),
        _row("---", "---", "---", "---", "---"),
    ]
    for d in report.items:
        notes = [d.error or "", "cached" if d.cached else "", "retried" if d.attempts == 2 else ""]
        if d.dropped_quotes:
            notes.append(f"{d.dropped_quotes} quote(s) dropped")
        lines.append(
            _row(
                d.item_id,
                ", ".join(d.expected),
                ", ".join(d.predicted) or "-",
                ", ".join(d.tags) or "-",
                ", ".join(n for n in notes if n) or "-",
            )
        )
    return "\n".join(lines) + "\n"


def write_report(report: Report, directory: Path = DEFAULT_REPORTS_DIR) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{report.run.started_at:%Y%m%dT%H%M%SZ}-{report.run.model}-{report.run.prompt_version}"
    json_path, md_path = directory / f"{stem}.json", directory / f"{stem}.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
