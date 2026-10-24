"""Evaluation reports: JSON for tools and comparisons, markdown for people.

Files go to backend/eval/reports/<set>/ (or `adhoc/` for `--data` and staging runs) as
`<UTC start>-<model>-<prompt>.json` and `.md`. A set run pins the set by name, hash and size.
"""

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.metrics import Scores, compute_scores
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.extractor.two_stage import StageUsage
from commitment_tracker.schemas import LEDGER_LABELS, Label, Precision, Span

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
    # Unset for `--data` runs and for reports written before named sets existed.
    set_name: str | None = None
    set_sha256: str | None = None
    set_items: int | None = None
    # The named configuration ("opus", "two-stage", ...) and the model behind each stage.
    configuration: str | None = None
    stages: dict[str, str] = Field(default_factory=dict)


class StageDetail(BaseModel):
    """One stage's share of a two-stage item: calls, wall-clock latency, tokens and cost."""

    stage: str
    model: str
    calls: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float | None

    @classmethod
    def from_usage(cls, usage: StageUsage) -> "StageDetail":
        return cls.model_validate(usage, from_attributes=True)


class PredictedSpan(BaseModel):
    """The parts of a predicted span that scoring reads, plus what a reader needs to judge it."""

    turn_index: int
    label: Label
    quote: str
    owner: str | None
    recipient: str | None
    action: str | None
    due_raw: str | None
    due_resolved: date | None
    precision: Precision
    condition: str | None

    @classmethod
    def from_span(cls, span: Span) -> "PredictedSpan":
        return cls(
            turn_index=span.turn_index,
            label=span.label,
            quote=span.quote,
            owner=span.owner,
            recipient=span.recipient,
            action=span.action,
            due_raw=span.due.raw,
            due_resolved=span.due.resolved,
            precision=span.due.precision,
            condition=span.condition,
        )


class ItemDetail(BaseModel):
    item_id: str
    tags: list[str]
    expected: list[str]
    predicted: list[str]
    error: str | None
    cached: bool
    attempts: int | None
    dropped_quotes: int | None
    # None in reports written before predictions were stored; those can't be re-scored.
    spans: list[PredictedSpan] | None = None
    provenance: str | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    served_by: str | None = None
    # Two-stage runs only.
    turns: int | None = None
    flagged_turns: list[int] | None = None
    stages: list[StageDetail] | None = None


class ProvenanceScore(BaseModel):
    items: int
    scored_items: int
    ledger_f1: float
    ledger_precision: float
    ledger_recall: float
    accuracy: float


class TwoStageScores(BaseModel):
    """How much the screen escalated, and what it let through.

    Escalation rate is flagged turns over all turns: on real calls it predicts the saving. A screen
    miss is an expected ledger span on a turn the screen did not flag, so the extract model never
    saw it; it is the number that says whether the cheap model is a safe screen.
    """

    turns: int
    flagged_turns: int
    escalation_rate: float
    screen_misses: int
    screen_miss_items: list[str]
    stage_cost_usd: dict[str, float | None]


class Report(BaseModel):
    run: RunInfo
    scores: Scores
    items: list[ItemDetail]
    by_provenance: dict[str, ProvenanceScore] = Field(default_factory=dict)
    two_stage: TwoStageScores | None = None


def _detail(r: ItemResult) -> ItemDetail:
    metadata = r.response.metadata if r.response else None
    return ItemDetail(
        item_id=r.item.id,
        tags=list(r.item.tags),
        expected=[span.label.value for span in r.item.expected],
        predicted=[span.label.value for span in r.response.spans] if r.response else [],
        error=r.error,
        cached=r.cached,
        attempts=metadata.attempts if metadata else None,
        dropped_quotes=metadata.dropped_quotes if metadata else None,
        spans=[PredictedSpan.from_span(span) for span in r.response.spans] if r.response else [],
        provenance=r.item.provenance,
        latency_ms=metadata.latency_ms if metadata else None,
        cost_usd=metadata.cost_usd if metadata else None,
        served_by=metadata.served_by if metadata else None,
        turns=len(r.item.turns) if r.flagged_turns is not None else None,
        flagged_turns=r.flagged_turns,
        stages=[StageDetail.from_usage(u) for u in r.stages] if r.stages is not None else None,
    )


def two_stage_scores(
    details: list[ItemDetail], items: dict[str, EvalItem]
) -> TwoStageScores | None:
    """Two-stage numbers from stored item details, so a re-score can rebuild them too."""
    staged = [d for d in details if d.flagged_turns is not None]
    if not staged:
        return None
    turns = sum(len(items[d.item_id].turns) for d in staged)
    flagged = sum(len(d.flagged_turns or []) for d in staged)
    missed: dict[str, int] = {}
    for detail in staged:
        flagged_set = set(detail.flagged_turns or [])
        count = sum(
            span.label in LEDGER_LABELS and span.turn_index not in flagged_set
            for span in items[detail.item_id].expected
        )
        if count:
            missed[detail.item_id] = count
    costs: dict[str, list[float | None]] = {}
    for detail in staged:
        for stage in detail.stages or []:
            costs.setdefault(stage.stage, []).append(stage.cost_usd)
    return TwoStageScores(
        turns=turns,
        flagged_turns=flagged,
        escalation_rate=flagged / turns if turns else 0.0,
        screen_misses=sum(missed.values()),
        screen_miss_items=sorted(missed),
        stage_cost_usd={
            stage: None if None in values else sum(v for v in values if v is not None)
            for stage, values in costs.items()
        },
    )


def scores_by_provenance(results: list[ItemResult]) -> dict[str, ProvenanceScore]:
    groups: dict[str, list[ItemResult]] = {}
    for result in results:
        groups.setdefault(result.item.provenance, []).append(result)
    breakdown = {}
    for provenance in sorted(groups):
        scores = compute_scores(groups[provenance])
        breakdown[provenance] = ProvenanceScore(
            items=scores.items,
            scored_items=scores.scored_items,
            ledger_f1=scores.ledger.f1,
            ledger_precision=scores.ledger.precision,
            ledger_recall=scores.ledger.recall,
            accuracy=scores.accuracy,
        )
    return breakdown


def build_report(run: RunInfo, results: list[ItemResult]) -> Report:
    served = sorted({r.response.metadata.served_by for r in results if r.response})
    details = [_detail(r) for r in results]
    return Report(
        run=run.model_copy(update={"served_by": served}),
        scores=compute_scores(results),
        items=details,
        by_provenance=scores_by_provenance(results),
        two_stage=two_stage_scores(details, {r.item.id: r.item for r in results}),
    )


def _f(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _dataset(run: RunInfo) -> str:
    if run.set_name and run.set_sha256:
        return f"set {run.set_name} (sha256 {run.set_sha256[:12]})"
    return run.dataset


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def render_markdown(report: Report) -> str:
    run, scores = report.run, report.scores
    ledger = scores.ledger
    lines = [
        f"# Evaluation: {run.model}, prompt {run.prompt_version}",
        "",
        f"{run.started_at:%Y-%m-%d %H:%M} UTC · {_dataset(run)} · {scores.items} items "
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
    if report.by_provenance:
        lines += [
            "",
            "## By provenance",
            "",
            "Who wrote the items: the same scores over each author's items alone.",
            "",
            _row(
                "Provenance", "Items", "Ledger F1", "Ledger precision", "Ledger recall", "Accuracy"
            ),
            _row("---", "---", "---", "---", "---", "---"),
        ]
        lines += [
            _row(
                name,
                p.items,
                _f(p.ledger_f1),
                _f(p.ledger_precision),
                _f(p.ledger_recall),
                _f(p.accuracy),
            )
            for name, p in report.by_provenance.items()
        ]
    if report.two_stage is not None:
        staged = report.two_stage
        stage_models = ", ".join(f"{k} {v}" for k, v in run.stages.items()) or "n/a"
        lines += [
            "",
            "## Two-stage",
            "",
            _row("Metric", "Value"),
            _row("---", "---"),
            _row("Stages", stage_models),
            _row(
                "Escalation rate",
                f"{_f(staged.escalation_rate)} ({staged.flagged_turns} of {staged.turns} turns)",
            ),
            _row("Screen misses", staged.screen_misses),
            _row("Items with a screen miss", ", ".join(staged.screen_miss_items) or "none"),
        ]
        lines += [
            _row(f"Cost, {stage}", f"${cost:.4f}" if cost is not None else "n/a")
            for stage, cost in staged.stage_cost_usd.items()
        ]
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
        _row("Configuration", run.configuration or run.model),
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
    # LF on every platform, so a report written on Windows diffs cleanly against one from CI.
    json_path.write_bytes((report.model_dump_json(indent=2) + "\n").encode("utf-8"))
    md_path.write_bytes(render_markdown(report).encode("utf-8"))
    return json_path, md_path
