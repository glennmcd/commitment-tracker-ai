"""Re-scoring committed reports from their stored predictions, with no model calls."""

import json
from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.report import Report, build_report, write_report
from commitment_tracker.evaluation.rescore import RescoreError, rescore, rescore_set
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.evaluation.sets import load_set
from commitment_tracker.schemas import Label
from tests.eval.builders import exp, item, pred, response
from tests.eval.test_report import RUN
from tests.eval.test_set_loading import write_set

COMMIT = item("c-1", ["I'll send it Friday."], [exp(0, "COMMITMENT", "I'll send it Friday.")])
TRAP = item("t-1", ["I promised that last year."], [exp(0, "NONE", "I promised that last year.")])


def results() -> list[ItemResult]:
    return [
        ItemResult(COMMIT, response(pred(0, "COMMITMENT", "I'll send it Friday.")), None, False),
        ItemResult(TRAP, response(pred(0, "COMMITMENT", "I promised that last year.")), None, True),
        ItemResult(
            item("f-1", ["Our SLA is four hours."], [exp(0, "NONE", "Our SLA is four hours.")]),
            None,
            "model_unavailable",
            False,
        ),
    ]


def test_rescoring_an_untouched_report_changes_nothing() -> None:
    report = build_report(RUN, results())
    again = rescore(report, {r.item.id: r.item for r in results()})
    assert again == report


def test_stale_scores_are_rebuilt_from_the_stored_spans() -> None:
    report = build_report(RUN, results())
    stale = report.model_copy(
        update={"scores": report.scores.model_copy(update={"accuracy": 0.123})}
    )
    assert rescore(stale, {r.item.id: r.item for r in results()}).scores == report.scores


def test_current_item_labels_are_used() -> None:
    report = build_report(RUN, results())
    relabelled = TRAP.model_copy(
        update={"expected": [TRAP.expected[0].model_copy(update={"label": Label.REPORTED})]}
    )
    items = {r.item.id: r.item for r in results()} | {"t-1": relabelled}
    assert rescore(report, items).scores.labels["REPORTED"].support == 1


def test_a_report_without_stored_spans_cannot_be_rescored() -> None:
    report = build_report(RUN, results())
    legacy = report.model_copy(
        update={"items": [d.model_copy(update={"spans": None}) for d in report.items]}
    )
    with pytest.raises(RescoreError, match="before predictions were stored"):
        rescore(legacy, {r.item.id: r.item for r in results()})


def test_an_item_missing_from_the_set_is_an_error() -> None:
    report = build_report(RUN, results())
    with pytest.raises(RescoreError, match="c-1"):
        rescore(report, {})


# --- a whole set's reports -----------------------------------------------------------------------


def set_up(tmp_path: Path) -> tuple[Path, Path, Path]:
    sets, reports = tmp_path / "sets", tmp_path / "reports"
    items = [r.item.model_dump(mode="json") for r in results()]
    write_set(sets, "test", items)
    loaded = load_set("test", sets)
    run = RUN.model_copy(
        update={"set_name": "test", "set_sha256": loaded.sha256, "set_items": len(items)}
    )
    json_path, _ = write_report(build_report(run, results()), reports / "test")
    return sets, reports, json_path


def tamper(json_path: Path) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["scores"]["ledger"]["f1"] = 0.5
    json_path.write_text(json.dumps(data), encoding="utf-8")


def test_rescore_set_rewrites_only_stale_reports(tmp_path: Path) -> None:
    sets, reports, json_path = set_up(tmp_path)
    tamper(json_path)
    (outcome,) = rescore_set("test", sets, reports)
    assert outcome.status == "updated"
    fixed = Report.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert fixed.scores.ledger.f1 != 0.5
    (again,) = rescore_set("test", sets, reports)
    assert again.status == "unchanged"


def test_reports_for_another_version_of_the_set_are_skipped(tmp_path: Path) -> None:
    sets, reports, json_path = set_up(tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["run"]["set_sha256"] = "0" * 64
    json_path.write_text(json.dumps(data), encoding="utf-8")
    (outcome,) = rescore_set("test", sets, reports)
    assert outcome.status == "skipped"
    assert "set changed" in outcome.reason


def test_cli_rescore(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sets, reports, json_path = set_up(tmp_path)
    tamper(json_path)
    argv = ["rescore", "--set", "test", "--sets-dir", str(sets), "--reports-dir", str(reports)]
    assert cli.main(argv) == 0
    assert f"updated   {json_path.name}" in capsys.readouterr().out
