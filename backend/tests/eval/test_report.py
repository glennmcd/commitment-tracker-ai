"""Reports: a JSON file for machines and a markdown summary for people, named by run."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from commitment_tracker.evaluation.report import (
    Report,
    RunInfo,
    build_report,
    render_markdown,
    write_report,
)
from commitment_tracker.evaluation.rescore import rescore
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.extractor.two_stage import StageUsage
from tests.eval.builders import exp, item, pred, response

COMMIT = item("c-1", ["I'll send it Friday."], [exp(0, "COMMITMENT", "I'll send it Friday.")])
SARCASM = item(
    "s-1",
    ["Sure, I'll rebuild it overnight."],
    [exp(0, "NONE", "Sure, I'll rebuild it overnight.")],
    tags=["ambiguous"],
)
RUN = RunInfo(
    model="claude-opus-5-5",
    prompt_version="v1",
    prompt_sha256="f" * 64,
    effort="medium",
    dataset="dev.jsonl",
    started_at=datetime(2026, 10, 21, 15, 30, tzinfo=UTC),
    duration_seconds=12.5,
)


def results() -> list[ItemResult]:
    return [
        ItemResult(COMMIT, response(pred(0, "COMMITMENT", "I'll send it Friday.")), None, False),
        ItemResult(
            SARCASM, response(pred(0, "COMMITMENT", "Sure, I'll rebuild it overnight.")), None, True
        ),
    ]


def test_report_holds_run_scores_and_items() -> None:
    report = build_report(RUN, results())
    assert report.run.model == "claude-opus-5-5"
    assert report.run.served_by == ["claude-opus-5-5"]
    assert report.scores.ledger.f1 == 1.0
    assert [d.item_id for d in report.items] == ["c-1", "s-1"]
    assert report.items[1].predicted == ["COMMITMENT"]
    assert report.items[1].cached


def test_markdown_summary_has_the_headline_sections() -> None:
    markdown = render_markdown(build_report(RUN, results()))
    assert markdown.startswith("# Evaluation: claude-opus-5-5, prompt v1")
    for heading in [
        "## Headline",
        "## Labels",
        "## Confusion matrix",
        "## Field accuracy",
        "## Ambiguous items",
        "## Run",
        "## Items",
    ]:
        assert heading in markdown, heading
    assert "| Ledger F1 | 1.000 |" in markdown
    assert "| s-1 | NONE | COMMITMENT |" in markdown


def test_write_report_names_files_by_time_model_and_prompt(tmp_path: Path) -> None:
    json_path, md_path = write_report(build_report(RUN, results()), tmp_path)
    assert json_path.name == "20261021T153000Z-claude-opus-5-5-v1.json"
    assert md_path.name == "20261021T153000Z-claude-opus-5-5-v1.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["scores"]["ledger"]["f1"] == 1.0
    assert md_path.read_text(encoding="utf-8").startswith("# Evaluation")


# --- predicted spans and provenance --------------------------------------------------------------

LEGACY = Path(__file__).resolve().parents[2] / "eval" / "reports" / "dev"


def test_items_keep_the_predicted_spans_scoring_reads() -> None:
    report = build_report(RUN, results())
    (span,) = report.items[0].spans or []
    assert (span.turn_index, span.label, span.quote) == (0, "COMMITMENT", "I'll send it Friday.")
    assert span.owner == "seller"
    assert report.items[0].latency_ms == 1_000
    assert report.items[0].cost_usd == 0.01
    assert report.items[0].provenance == "hand-written"


def test_a_failed_item_has_no_spans_but_keeps_its_error() -> None:
    report = build_report(RUN, [ItemResult(COMMIT, None, "model_unavailable", False)])
    assert report.items[0].spans == []
    assert report.items[0].error == "model_unavailable"


def test_scores_are_broken_down_by_provenance() -> None:
    gemini = COMMIT.model_copy(update={"id": "g-1", "provenance": "gemini-3-pro"})
    report = build_report(
        RUN,
        [
            ItemResult(
                COMMIT, response(pred(0, "COMMITMENT", "I'll send it Friday.")), None, False
            ),
            ItemResult(gemini, response(pred(0, "NONE", "I'll send it Friday.")), None, False),
        ],
    )
    assert set(report.by_provenance) == {"gemini-3-pro", "hand-written"}
    assert report.by_provenance["hand-written"].ledger_f1 == 1.0
    assert report.by_provenance["gemini-3-pro"].ledger_f1 == 0.0
    assert report.by_provenance["gemini-3-pro"].items == 1
    assert "## By provenance" in render_markdown(report)


def test_reports_written_before_spans_were_stored_still_load() -> None:
    for path in LEGACY.glob("*.json"):
        report = Report.model_validate_json(path.read_text(encoding="utf-8"))
        assert report.items and report.items[0].spans is None
        assert report.by_provenance == {}


# --- two-stage -----------------------------------------------------------------------------------


def stage(name: str, cost: float | None) -> StageUsage:
    return StageUsage(
        stage=name,
        model="m",
        calls=1,
        latency_ms=10,
        input_tokens=1,
        output_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        cost_usd=cost,
    )


def staged_results() -> list[ItemResult]:
    two_turns = item(
        "m-1",
        ["Can you send it?", "I'll send it Friday."],
        [exp(0, "REQUEST", "Can you send it?"), exp(1, "COMMITMENT", "I'll send it Friday.")],
    )
    missed = item(
        "m-2", ["Fine.", "We'll ship Monday."], [exp(1, "COMMITMENT", "We'll ship Monday.")]
    )
    return [
        ItemResult(
            two_turns,
            response(pred(1, "COMMITMENT", "I'll send it Friday.")),
            None,
            False,
            stages=[stage("screen", 0.001), stage("extract", 0.01)],
            flagged_turns=[0, 1],
        ),
        ItemResult(
            missed,
            response(pred(1, "NONE", "We'll ship Monday.")),
            None,
            False,
            stages=[stage("screen", 0.001)],
            flagged_turns=[],
        ),
    ]


def test_two_stage_reports_escalation_and_screen_misses() -> None:
    report = build_report(RUN, staged_results())
    staged = report.two_stage
    assert staged is not None
    assert (staged.turns, staged.flagged_turns) == (4, 2)
    assert staged.escalation_rate == 0.5
    assert (staged.screen_misses, staged.screen_miss_items) == (1, ["m-2"])
    assert staged.stage_cost_usd == pytest.approx({"screen": 0.002, "extract": 0.01})
    assert report.items[0].stages is not None and report.items[0].turns == 2
    markdown = render_markdown(report)
    assert "## Two-stage" in markdown
    assert "| Escalation rate | 0.500 (2 of 4 turns) |" in markdown


def test_single_model_reports_have_no_two_stage_section() -> None:
    report = build_report(RUN, results())
    assert report.two_stage is None
    assert "## Two-stage" not in render_markdown(report)


def test_rescore_rebuilds_the_two_stage_numbers() -> None:
    report = build_report(RUN, staged_results())
    stale = report.model_copy(update={"two_stage": None})
    items = {r.item.id: r.item for r in staged_results()}
    assert rescore(stale, items) == report
