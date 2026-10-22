"""Reports: a JSON file for machines and a markdown summary for people, named by run."""

import json
from datetime import UTC, datetime
from pathlib import Path

from commitment_tracker.evaluation.report import (
    RunInfo,
    build_report,
    render_markdown,
    write_report,
)
from commitment_tracker.evaluation.results import ItemResult
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
