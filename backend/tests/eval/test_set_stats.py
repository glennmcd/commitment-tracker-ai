"""`uv run eval-stats`: spans per label and items per provenance, with thin labels flagged."""

import json
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation import stats_cli
from commitment_tracker.evaluation.sets import SETS_DIR, summarize
from commitment_tracker.evaluation.stats import label_counts, thin_labels
from commitment_tracker.schemas import Label
from tests.eval.builders import exp
from tests.eval.test_dataset import item_data
from tests.eval.test_set_loading import write_set

ALL_LABELS = [label.value for label in Label]


def item_with_labels(item_id: str, labels: list[str], **overrides: Any) -> dict[str, Any]:
    """One turn per label, each holding one expected span of that label."""
    turns = [
        {"speaker": "seller", "text": f"Line {n} about {label}."} for n, label in enumerate(labels)
    ]
    expected = [exp(n, label, f"Line {n} about {label}.") for n, label in enumerate(labels)]
    return item_data(id=item_id, turns=turns, expected=expected, **overrides)


def populate(root: Path) -> None:
    write_set(
        root,
        "dev",
        [item_data(), item_with_labels("x-02", ["COMMITMENT", "NONE"])],
        role="dev",
        gated=False,
    )
    write_set(root, "test", [item_with_labels(f"t-{n:02}", ALL_LABELS) for n in range(2)])
    write_set(
        root,
        "staging/gem01",
        [item_data(id="g-01", provenance="gemini-3-pro", review="unreviewed")],
        role="staging",
        gated=False,
    )


def summary_named(root: Path, name: str) -> Any:
    return next(summary for summary in summarize(root) if summary.name == name)


def test_counts_match_a_count_taken_straight_from_the_set_file() -> None:
    lines = (SETS_DIR / "test" / "items.jsonl").read_text(encoding="utf-8").splitlines()
    items = [json.loads(line) for line in lines if line.strip()]
    expected = {label: 0 for label in ALL_LABELS}
    provenance: dict[str, int] = {}
    for item in items:
        provenance[item["provenance"]] = provenance.get(item["provenance"], 0) + 1
        for span in item["expected"]:
            expected[span["label"]] += 1
    test = next(summary for summary in summarize() if summary.name == "test")
    assert label_counts(test) == expected
    assert test.provenance == provenance


def test_every_label_is_listed_even_when_it_has_no_spans(tmp_path: Path) -> None:
    populate(tmp_path)
    counts = label_counts(summary_named(tmp_path, "dev"))
    assert list(counts) == ALL_LABELS
    assert counts["HEDGED"] == 0
    assert counts["COMMITMENT"] == 2


def test_thin_labels_are_those_under_the_floor_including_absent_ones(tmp_path: Path) -> None:
    populate(tmp_path)
    dev = summary_named(tmp_path, "dev")
    assert thin_labels(dev, floor=1) == [
        label for label in ALL_LABELS if label not in {"COMMITMENT", "NONE"}
    ]
    assert thin_labels(dev, floor=3) == ALL_LABELS
    assert thin_labels(dev, floor=2) == [label for label in ALL_LABELS if label != "COMMITMENT"]


def test_print_shows_each_label_thin_marks_and_the_provenance_mix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    populate(tmp_path)
    assert stats_cli.stats_main(["--sets-dir", str(tmp_path), "--set", "dev"]) == 0
    out = capsys.readouterr().out
    assert "dev  role dev  gated no  items 2" in out
    assert "  COMMITMENT    2  thin\n" in out
    assert "  HEDGED        0  thin\n" in out
    assert "  under 10      HEDGED" not in out
    assert "  under 10      " in out
    assert "  provenance    hand-written 2\n" in out


def test_strict_exits_1_when_a_label_is_under_the_floor(tmp_path: Path) -> None:
    populate(tmp_path)
    # The test set holds two spans of each label: thin at the default floor of 10, clear at 2.
    assert stats_cli.stats_main(["--sets-dir", str(tmp_path), "--set", "test", "--strict"]) == 1
    assert (
        stats_cli.stats_main(
            ["--sets-dir", str(tmp_path), "--set", "test", "--strict", "--floor", "2"]
        )
        == 0
    )
    assert (
        stats_cli.stats_main(
            ["--sets-dir", str(tmp_path), "--set", "test", "--strict", "--floor", "3"]
        )
        == 1
    )


def test_without_strict_a_thin_set_still_exits_0(tmp_path: Path) -> None:
    populate(tmp_path)
    assert stats_cli.stats_main(["--sets-dir", str(tmp_path), "--set", "dev"]) == 0


def test_strict_leaves_staging_sets_unjudged_unless_named(tmp_path: Path) -> None:
    populate(tmp_path)
    write_set(
        tmp_path,
        "dev",
        [item_with_labels(f"d-{n:02}", ALL_LABELS) for n in range(5)],
        role="dev",
        gated=False,
    )
    write_set(tmp_path, "test", [item_with_labels(f"t-{n:02}", ALL_LABELS) for n in range(5)])
    assert stats_cli.stats_main(["--sets-dir", str(tmp_path), "--strict", "--floor", "5"]) == 0
    assert (
        stats_cli.stats_main(["--sets-dir", str(tmp_path), "--set", "staging/gem01", "--strict"])
        == 1
    )


def test_an_unknown_set_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    populate(tmp_path)
    assert stats_cli.stats_main(["--sets-dir", str(tmp_path), "--set", "nope"]) == 1
    assert "no text set named 'nope'" in capsys.readouterr().err


def test_a_broken_set_exits_1(tmp_path: Path) -> None:
    populate(tmp_path)
    (tmp_path / "test" / "items.jsonl").write_text("{nope\n", encoding="utf-8")
    assert stats_cli.stats_main(["--sets-dir", str(tmp_path)]) == 1


def test_audio_sets_have_no_spans_and_are_not_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    populate(tmp_path)
    write_set(tmp_path, "audio", [], kind="audio", items_from="test", role="test", gated=False)
    (tmp_path / "audio" / "clips.jsonl").write_text("", encoding="utf-8")
    assert stats_cli.stats_main(["--sets-dir", str(tmp_path)]) == 0
    assert "audio  role" not in capsys.readouterr().out


def test_the_committed_test_set_is_thin_at_10_and_not_at_5() -> None:
    assert stats_cli.stats_main(["--set", "test", "--strict"]) == 1
    assert stats_cli.stats_main(["--set", "test", "--strict", "--floor", "5"]) == 0


def test_a_negative_floor_is_refused() -> None:
    with pytest.raises(SystemExit):
        stats_cli.stats_main(["--floor", "-1"])
