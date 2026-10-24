"""`uv run eval-compare`: score changes between two runs on one set, and which items flipped."""

from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.compare import CompareError, compare, item_correct
from commitment_tracker.evaluation.report import Report, build_report, write_report
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.evaluation.sets import load_set
from tests.eval.builders import exp, item, pred, response
from tests.eval.test_report import RUN
from tests.eval.test_set_loading import write_set

A = item("a", ["I'll send it Friday."], [exp(0, "COMMITMENT", "I'll send it Friday.")])
B = item("b", ["I might send it."], [exp(0, "HEDGED", "I might send it.")])
C = item("c", ["Our SLA is four hours."], [exp(0, "NONE", "Our SLA is four hours.")])
ITEMS = {i.id: i for i in (A, B, C)}


def run_of(model: str, labels: dict[str, str], minute: int = 0) -> Report:
    results = [
        ItemResult(
            ITEMS[item_id], response(pred(0, label, ITEMS[item_id].turns[0].text)), None, False
        )
        for item_id, label in labels.items()
    ]
    run = RUN.model_copy(
        update={
            "model": model,
            "configuration": model,
            "set_name": "test",
            "set_sha256": "f" * 64,
            "started_at": RUN.started_at.replace(minute=minute),
        }
    )
    return build_report(run, results)


BEFORE = run_of("haiku", {"a": "COMMITMENT", "b": "COMMITMENT", "c": "NONE"})
AFTER = run_of("opus", {"a": "HEDGED", "b": "HEDGED", "c": "NONE"}, minute=1)


def test_item_correct_needs_every_label_right_and_no_extra_ledger_spans() -> None:
    assert item_correct(A, [pred(0, "COMMITMENT", "I'll send it Friday.")])
    assert not item_correct(A, [pred(0, "HEDGED", "I'll send it Friday.")])
    assert not item_correct(A, [])
    assert not item_correct(C, [pred(0, "COMMITMENT", "Our SLA is four hours.")])
    assert item_correct(C, [])


def test_compare_lists_flips_both_ways() -> None:
    comparison = compare(BEFORE, AFTER, ITEMS)
    assert comparison.regressions == ["a"]
    assert comparison.fixes == ["b"]
    assert comparison.both_right == 1
    assert comparison.both_wrong == 0


def test_compare_reports_score_deltas() -> None:
    comparison = compare(BEFORE, AFTER, ITEMS)
    deltas = {d.metric: d for d in comparison.deltas}
    ledger = deltas["ledger F1"]
    assert (ledger.a, ledger.b) == (BEFORE.scores.ledger.f1, AFTER.scores.ledger.f1)
    assert ledger.change == pytest.approx(AFTER.scores.ledger.f1 - BEFORE.scores.ledger.f1)
    assert "F1 HEDGED" in deltas


def test_runs_on_different_sets_are_refused() -> None:
    other = AFTER.model_copy(update={"run": AFTER.run.model_copy(update={"set_sha256": "0" * 64})})
    with pytest.raises(CompareError, match="different versions"):
        compare(BEFORE, other, ITEMS)


def test_reports_without_spans_are_refused() -> None:
    legacy = BEFORE.model_copy(
        update={"items": [d.model_copy(update={"spans": None}) for d in BEFORE.items]}
    )
    with pytest.raises(CompareError, match="predictions"):
        compare(legacy, AFTER, ITEMS)


def test_cli_compares_two_reports_by_path_or_stem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sets, reports = tmp_path / "sets", tmp_path / "reports"
    write_set(sets, "test", [i.model_dump(mode="json") for i in ITEMS.values()])
    sha = load_set("test", sets).sha256
    paths = []
    for report in (BEFORE, AFTER):
        pinned = report.model_copy(
            update={"run": report.run.model_copy(update={"set_sha256": sha})}
        )
        paths.append(write_report(pinned, reports / "test")[0])
    argv = [str(paths[0]), paths[1].stem, "--sets-dir", str(sets), "--reports-dir", str(reports)]
    assert cli.compare_main(argv) == 0
    out = capsys.readouterr().out
    assert "right to wrong (1): a" in out
    assert "wrong to right (1): b" in out
    assert "ledger F1" in out
