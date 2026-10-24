"""`uv run eval-sets`: one block per set with role, size, review state, label and provenance mix."""

from pathlib import Path

import pytest

from commitment_tracker.evaluation import sets
from commitment_tracker.evaluation.sets import summarize
from tests.eval.builders import exp
from tests.eval.test_dataset import item_data
from tests.eval.test_set_loading import write_set

TWO_SPANS = [exp(0, "COMMITMENT", "I'll send it Friday."), exp(0, "NONE", "Friday")]


def populate(root: Path) -> None:
    write_set(
        root,
        "dev",
        [item_data(), item_data(id="x-02", provenance="claude-opus-5-5", expected=TWO_SPANS)],
        role="dev",
        gated=False,
    )
    write_set(root, "test", [])
    write_set(
        root,
        "staging/gem01",
        [item_data(id="g-01", provenance="gemini-3-pro", review="unreviewed")],
        role="staging",
        gated=False,
    )


def test_summary_counts_reviews_labels_and_provenance(tmp_path: Path) -> None:
    populate(tmp_path)
    dev, staging, test = summarize(tmp_path)
    assert (dev.name, dev.role, dev.gated, dev.items) == ("dev", "dev", False, 2)
    assert dev.review == {"accepted": 2}
    assert dev.labels == {"COMMITMENT": 2, "NONE": 1}
    assert dev.provenance == {"claude-opus-5-5": 1, "hand-written": 1}
    assert len(dev.sha256) == 64
    assert staging.review == {"unreviewed": 1}
    assert (test.items, test.gated) == (0, True)


def test_labels_are_listed_in_label_order(tmp_path: Path) -> None:
    populate(tmp_path)
    dev = summarize(tmp_path)[0]
    assert list(dev.labels) == ["COMMITMENT", "NONE"]


def test_a_broken_set_is_reported_not_raised(tmp_path: Path) -> None:
    populate(tmp_path)
    (tmp_path / "test" / "items.jsonl").write_text("{nope\n", encoding="utf-8")
    test = summarize(tmp_path)[2]
    assert test.error is not None
    assert "line 1" in test.error


def test_cli_prints_a_block_per_set(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    populate(tmp_path)
    assert sets.main(["--sets-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "dev  role dev  gated no  items 2  sha256 " in out
    assert "test  role test  gated yes  items 0" in out
    assert "labels      COMMITMENT 2, NONE 1" in out
    assert "provenance  claude-opus-5-5 1, hand-written 1" in out
    assert "review      unreviewed 1" in out


def test_cli_exits_1_when_a_set_is_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    populate(tmp_path)
    (tmp_path / "test" / "items.jsonl").write_text("{nope\n", encoding="utf-8")
    assert sets.main(["--sets-dir", str(tmp_path)]) == 1
    assert "error" in capsys.readouterr().out
