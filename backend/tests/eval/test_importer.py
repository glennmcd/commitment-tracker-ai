"""`uv run eval import`: drafted items into a staging batch, with every rejection and date check."""

import json
from datetime import date
from pathlib import Path
from typing import Any

from commitment_tracker.evaluation.dataset import EvalItem, jsonl_lines
import pytest
import logging



from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.importer import (
    BatchError,
    ImportReport,
    ImportResult,
    import_batch,
    check_batch,
    latest_generation_prompt,
)
from commitment_tracker.evaluation.sets import load_set
from tests.eval.test_set_loading import write_set

TODAY = date(2026, 10, 25)
logger = logging.getLogger(__name__)

def draft(item_id: str, text: str = "I'll send it Friday.", **overrides: Any) -> dict[str, Any]:
    """A line as a generator writes it: no provenance, no review."""
    data: dict[str, Any] = {
        "id": item_id,
        "call_date": "2026-10-21",
        "turns": [{"speaker": "seller", "text": text}],
        "tags": [],
        "expected": [
            {
                "turn_index": 0,
                "label": "COMMITMENT",
                "quote": text,
                "owner": "seller",
                "recipient": "buyer",
                "action_keywords": ["send"],
                "due_raw": "Friday",
                "due_resolved": "2026-10-23",
                "precision": "day",
                "condition": None,
            }
        ],
        "note": None,
    }
    data.update(overrides)
    return data


# this fixture sets up a root directory with a dev set containing one item 
# and is passed into the test functions
@pytest.fixture
def root(tmp_path: Path) -> Path:
    logger.debug("Setting up root directory at %s", tmp_path)
    sets = tmp_path / "sets"
    write_set(
        sets,
        "dev",
        [
            {
                **draft("d-01", "Our SLA is four hours for every priority one ticket."),
                "expected": [
                    {
                        "turn_index": 0,
                        "label": "NONE",
                        "quote": "Our SLA is four hours for every priority one ticket.",
                    }
                ],
                "provenance": "spec",
                "review": "accepted",
            }
        ],
        role="dev",
        gated=False,
    )
    return sets


def write_source(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "gemini.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def standard_options(root: Path, **overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "batch": "gem01",
        "provenance": "gemini-3-pro",
        "generation_prompt": "prompt-v1",
        "root": root,
        "today": TODAY,
    }
    options.update(overrides)
    return options

def run_check(jsonl_lines: list[str], source_name: str, root: Path, **overrides: Any) -> tuple[ImportReport, list[tuple[EvalItem, str]]]:
    options = standard_options(root, **overrides)
    return check_batch(jsonl_lines,source_name=source_name, **options)

def run(source: Path, root: Path, **overrides: Any) -> ImportResult:
    options = standard_options(root, **overrides)
    import_result,_ = import_batch(source, **options)
    return import_result

# splitting out check_batch from import_batch
# the tests use a common run function to call import_batch with consistent options
def test_check_batch_returns_import_report(tmp_path: Path, root: Path) -> None:
    source = write_source(tmp_path, "```jsonl", "", json.dumps(draft("gem01-01")), "```")
    report, accepted = run_check(jsonl_lines(source), source.name, root)
    assert report.imported == 1

def test_valid_lines_land_in_staging_unreviewed(tmp_path: Path, root: Path) -> None:
    source = write_source(
        tmp_path,
        json.dumps(draft("gem01-01")),
        json.dumps(
            draft(
                "gem01-02",
                "We'll ship the build by end of next week.",
                expected=[
                    {
                        **draft("x")["expected"][0],
                        "quote": "We'll ship the build by end of next week.",
                        "action_keywords": ["ship"],
                        "due_raw": "by end of next week",
                        "due_resolved": "2026-10-30",
                    }
                ],
            )
        ),
    )
    result = run(source, root)
    assert result.imported == ["gem01-01", "gem01-02"]
    assert result.rejections == []
    staged = load_set("staging/gem01", root)
    assert {item.review for item in staged.items} == {"unreviewed"}
    assert {item.provenance for item in staged.items} == {"gemini-3-pro"}
    (source_entry,) = staged.manifest.sources
    assert source_entry.batch == "gem01"
    assert source_entry.generation_prompt == "prompt-v1"
    assert source_entry.imported == TODAY
    assert source_entry.call_date == date(2026, 10, 21)
    assert source_entry.items == 2
    report = json.loads((root / "staging" / "gem01" / "import.json").read_text("utf-8"))
    assert report["imported"] == 2


def test_fences_and_blank_lines_are_skipped(tmp_path: Path, root: Path) -> None:
    source = write_source(tmp_path, "```jsonl", "", json.dumps(draft("gem01-01")), "```")
    assert run(source, root).imported == ["gem01-01"]


def test_every_bad_line_is_rejected_with_its_number(tmp_path: Path, root: Path) -> None:
    source = write_source(
        tmp_path,
        "{nope",
        json.dumps(draft("gem01-02", expected=[{**draft("x")["expected"][0], "quote": "absent"}])),
        json.dumps(draft("gem01-03")),
        json.dumps(draft("gem01-03", "I'll send the deck tomorrow, promise.")),
        json.dumps({**draft("gem01-05"), "surprise": 1}),
    )
    result = run(source, root)
    assert result.imported == ["gem01-03"]
    reasons = {r.line: r.reason for r in result.rejections}
    assert set(reasons) == {1, 2, 4, 5}
    assert "JSON" in reasons[1] or "json" in reasons[1]
    assert "quote is not in turn 0" in reasons[2]
    assert "duplicate id gem01-03" in reasons[4]
    assert "Extra inputs" in reasons[5]


def test_an_id_already_in_a_set_is_rejected(tmp_path: Path, root: Path) -> None:
    source = write_source(tmp_path, json.dumps(draft("d-01", "Totally new text for this one.")))
    result = run(source, root)
    assert result.imported == []
    assert result.rejections[0].reason == "duplicate id d-01"
    assert not (root / "staging").exists()


def test_exact_duplicates_of_existing_items_are_dropped(tmp_path: Path, root: Path) -> None:
    text = "our sla is FOUR hours for every priority-one ticket"
    dup = draft("gem01-01", text, expected=[{"turn_index": 0, "label": "NONE", "quote": text}])
    source = write_source(tmp_path, json.dumps(dup), json.dumps(draft("gem01-02")))
    result = run(source, root)
    assert result.imported == ["gem01-02"]
    assert "same transcript as dev:d-01" in result.rejections[0].reason


def test_near_duplicates_are_flagged_not_dropped(tmp_path: Path, root: Path) -> None:
    text = "Our SLA is four hours for every priority two ticket."
    near = draft("gem01-01", text, expected=[{"turn_index": 0, "label": "NONE", "quote": text}])
    result = run(write_source(tmp_path, json.dumps(near)), root)
    assert result.imported == ["gem01-01"]
    (flag,) = result.near_duplicates
    assert (flag.item, flag.of) == ("gem01-01", "dev:d-01")
    assert flag.ratio >= 0.85


def test_resolver_disagreements_are_recorded_and_the_generator_date_kept(
    tmp_path: Path, root: Path
) -> None:
    wrong = draft(
        "gem01-01", expected=[{**draft("x")["expected"][0], "due_resolved": "2026-10-30"}]
    )
    result = run(write_source(tmp_path, json.dumps(wrong)), root)
    (disagreement,) = result.date_disagreements
    assert disagreement.model_dump(mode="json") == {
        "item": "gem01-01",
        "span": 0,
        "generator": "2026-10-30",
        "resolver": "2026-10-23",
    }
    staged = load_set("staging/gem01", root)
    assert staged.items[0].expected[0].due_resolved == date(2026, 10, 30)


def test_an_existing_batch_is_never_overwritten(tmp_path: Path, root: Path) -> None:
    source = write_source(tmp_path, json.dumps(draft("gem01-01")))
    run(source, root)
    with pytest.raises(BatchError, match="already exists"):
        run(source, root)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"batch": "Gem 01"}, "batch"),
        ({"provenance": "Gemini"}, "provenance"),
        ({"provenance": "spec"}, "spec"),
    ],
)
def test_bad_options_are_rejected(
    tmp_path: Path, root: Path, overrides: dict[str, str], message: str
) -> None:
    source = write_source(tmp_path, json.dumps(draft("gem01-01")))
    with pytest.raises(BatchError, match=message):
        run(source, root, **overrides)


def test_hand_written_batches_have_no_generation_prompt(tmp_path: Path, root: Path) -> None:
    source = write_source(tmp_path, json.dumps(draft("hand01-01")))
    run(source, root, batch="hand01", provenance="hand-written")
    (entry,) = load_set("staging/hand01", root).manifest.sources
    assert entry.generation_prompt is None


def test_latest_generation_prompt(tmp_path: Path) -> None:
    for name in ["prompt-v1.md", "prompt-v10.md", "prompt-v2.md", "notes.md"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert latest_generation_prompt(tmp_path) == "prompt-v10"


def test_cli_import(tmp_path: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = write_source(tmp_path, json.dumps(draft("gem01-01")), "{nope")
    argv = ["import", str(source), "--batch", "gem01", "--provenance", "gemini-3-pro"]
    assert cli.main([*argv, "--sets-dir", str(root)]) == 0
    out = capsys.readouterr().out
    assert "imported 1" in out
    assert "line 2:" in out
    assert (root / "staging" / "gem01" / "items.jsonl").is_file()


def test_cli_import_with_nothing_valid_exits_1(
    tmp_path: Path, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_source(tmp_path, "{nope")
    argv = ["import", str(source), "--batch", "gem01", "--provenance", "gemini-3-pro"]
    assert cli.main([*argv, "--sets-dir", str(root)]) == 1
    captured = capsys.readouterr()
    assert "nothing to import" in captured.err
    assert "line 1: invalid JSON" in captured.out
    assert not (root / "staging").exists()


def test_a_byte_order_mark_does_not_break_the_first_line(tmp_path: Path, root: Path) -> None:
    source = tmp_path / "powershell.jsonl"
    source.write_bytes(("\ufeff" + json.dumps(draft("gem01-01")) + "\n").encode("utf-8"))
    assert run(source, root).imported == ["gem01-01"]


def test_a_line_separator_inside_a_transcript_survives_import(tmp_path: Path, root: Path) -> None:
    text = "I'll send it Friday.\u2028Thanks again."
    line = json.dumps(draft("gem01-01", text), ensure_ascii=False)
    source = tmp_path / "reply.jsonl"
    source.write_bytes((line + "\n").encode("utf-8"))
    assert run(source, root).imported == ["gem01-01"]
    staged = load_set("staging/gem01", root)
    assert staged.items[0].turns[0].text == text


def test_long_near_duplicates_are_still_flagged(tmp_path: Path, root: Path) -> None:
    long = " ".join(
        f"We reviewed item {n} of the rollout plan with the onboarding team." for n in range(8)
    )
    first = draft("gem01-01", long, expected=[{"turn_index": 0, "label": "NONE", "quote": long}])
    changed = long.replace("item 3", "item three")
    second = draft(
        "gem01-02", changed, expected=[{"turn_index": 0, "label": "NONE", "quote": changed}]
    )
    result = run(write_source(tmp_path, json.dumps(first), json.dumps(second)), root)
    assert [flag.item for flag in result.near_duplicates] == ["gem01-02"]
