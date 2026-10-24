"""`uv run eval review`: blind labels first, then the generator's, with resumable progress."""

import json
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.importer import import_batch
from commitment_tracker.evaluation.review import ReviewIO, load_reviews, review_batch
from commitment_tracker.evaluation.sets import load_set
from commitment_tracker.schemas import Label
from tests.eval.test_importer import draft
from tests.eval.test_set_loading import write_set

NOTE = "generator note: the reply binds the seller"


class Terminal:
    """Scripted answers in order; records everything printed."""

    def __init__(self, *answers: str, edits: list[Callable[[Path], None]] | None = None) -> None:
        self.answers = deque(answers)
        self.edits = deque(edits or [])
        self.lines: list[str] = []

    def input(self, prompt: str) -> str:
        self.lines.append(prompt)
        if not self.answers:
            raise AssertionError(f"no scripted answer for {prompt!r}")
        return self.answers.popleft()

    def print(self, text: str) -> None:
        self.lines.append(text)

    def edit(self, path: Path) -> None:
        self.edits.popleft()(path)

    def io(self) -> ReviewIO:
        return ReviewIO(
            input=self.input,
            print=self.print,
            edit=self.edit,
            now=lambda: datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        )

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def two_span_draft(item_id: str, thing: str = "deck", **overrides: Any) -> dict[str, Any]:
    text_a, text_b = f"Can you send the {thing}?", "Sure, I'll send it Friday."
    data = draft(
        item_id,
        turns=[{"speaker": "buyer", "text": text_a}, {"speaker": "seller", "text": text_b}],
        expected=[
            {"turn_index": 0, "label": "REQUEST", "quote": text_a, "recipient": "buyer"},
            {
                **draft("x")["expected"][0],
                "turn_index": 1,
                "quote": text_b,
                "due_raw": "Friday",
                "due_resolved": "2026-10-23",
            },
        ],
        note=NOTE,
    )
    data.update(overrides)
    return data


@pytest.fixture
def root(tmp_path: Path) -> Path:
    sets = tmp_path / "sets"
    write_set(sets, "dev", [], role="dev", gated=False)
    return sets


def stage(tmp_path: Path, root: Path, *items: dict[str, Any]) -> None:
    source = tmp_path / "reply.jsonl"
    source.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    import_batch(
        source,
        batch="gem01",
        provenance="gemini-3-pro",
        generation_prompt="prompt-v1",
        root=root,
        today=date(2026, 10, 24),
    )


def staged(root: Path) -> dict[str, Any]:
    return {item.id: item for item in load_set("staging/gem01", root).items}


def test_agreeing_labels_accept_on_enter(tmp_path: Path, root: Path) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    terminal = Terminal("r", "c", "")
    summary = review_batch("gem01", root, terminal.io())
    assert summary.accepted == 1
    item = staged(root)["gem01-01"]
    assert item.review == "accepted"
    (record,) = load_reviews(root / "staging" / "gem01")
    assert record.outcome == "accepted"
    assert [(s.mine, s.generator) for s in record.spans] == [
        (Label.REQUEST, Label.REQUEST),
        (Label.COMMITMENT, Label.COMMITMENT),
    ]
    assert record.decided_at == datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def test_provenance_and_note_stay_hidden_until_the_item_is_decided(
    tmp_path: Path, root: Path
) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    terminal = Terminal("r", "c", "")
    review_batch("gem01", root, terminal.io())
    decided = next(i for i, line in enumerate(terminal.lines) if line.startswith("decided"))
    before = "\n".join(terminal.lines[:decided])
    assert "gemini" not in before
    assert NOTE not in before
    assert "gemini-3-pro" in terminal.lines[decided]


def test_taking_my_label_edits_the_item(tmp_path: Path, root: Path) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    terminal = Terminal("r", "h", "m")
    summary = review_batch("gem01", root, terminal.io())
    assert summary.edited == 1
    item = staged(root)["gem01-01"]
    assert item.review == "edited"
    assert item.expected[1].label is Label.HEDGED
    assert NOTE in terminal.text  # a disagreement shows the generator's note
    (record,) = load_reviews(root / "staging" / "gem01")
    assert (record.spans[1].mine, record.spans[1].generator) == (Label.HEDGED, Label.COMMITMENT)
    assert record.spans[1].final is Label.HEDGED


def test_keeping_the_generator_label_accepts_but_records_the_disagreement(
    tmp_path: Path, root: Path
) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    review_batch("gem01", root, Terminal("r", "h", "g").io())
    assert staged(root)["gem01-01"].expected[1].label is Label.COMMITMENT
    (record,) = load_reviews(root / "staging" / "gem01")
    assert record.outcome == "accepted"
    assert record.spans[1].mine is Label.HEDGED


def test_rejected_items_stay_unreviewed(tmp_path: Path, root: Path) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    summary = review_batch("gem01", root, Terminal("n", "c", "r").io())
    assert summary.rejected == 1
    assert staged(root)["gem01-01"].review == "unreviewed"
    assert load_reviews(root / "staging" / "gem01")[0].outcome == "rejected"


def test_unknown_keys_are_asked_again(tmp_path: Path, root: Path) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    terminal = Terminal("z", "r", "c", "")
    assert review_batch("gem01", root, terminal.io()).accepted == 1
    assert "unknown key" in terminal.text


def test_quitting_keeps_decided_items_and_resume_skips_them(tmp_path: Path, root: Path) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"), two_span_draft("gem01-02", "contract"))
    first = review_batch("gem01", root, Terminal("r", "c", "", "q").io())
    assert (first.accepted, first.remaining) == (1, 1)
    second = Terminal("r", "c", "")
    resumed = review_batch("gem01", root, second.io())
    assert (resumed.accepted, resumed.remaining) == (1, 0)
    assert "gem01-02" in second.text and "item 1 of 1" in second.text
    assert {item.review for item in staged(root).values()} == {"accepted"}


def test_resolver_disagreement_can_take_the_resolver_date(tmp_path: Path, root: Path) -> None:
    wrong = two_span_draft("gem01-01")
    wrong["expected"][1]["due_resolved"] = "2026-10-30"
    stage(tmp_path, root, wrong)
    terminal = Terminal("r", "c", "v")
    assert review_batch("gem01", root, terminal.io()).edited == 1
    assert "2026-10-30" in terminal.text and "2026-10-23" in terminal.text
    assert staged(root)["gem01-01"].expected[1].due_resolved == date(2026, 10, 23)
    (record,) = load_reviews(root / "staging" / "gem01")
    assert record.dates[0].verdict == "resolver"


def test_siding_with_the_generator_asks_for_a_resolver_test(tmp_path: Path, root: Path) -> None:
    wrong = two_span_draft("gem01-01")
    wrong["expected"][1]["due_resolved"] = "2026-10-30"
    stage(tmp_path, root, wrong)
    terminal = Terminal("r", "c", "g")
    assert review_batch("gem01", root, terminal.io()).accepted == 1
    assert "test_dates.py" in terminal.text
    assert staged(root)["gem01-01"].expected[1].due_resolved == date(2026, 10, 30)


def rewrite_note(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["note"] = "fixed by hand"
    path.write_text(json.dumps(data), encoding="utf-8")


def break_quote(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expected"][0]["quote"] = "not in the turn"
    path.write_text(json.dumps(data), encoding="utf-8")


def test_editing_in_the_editor_marks_the_item_edited(tmp_path: Path, root: Path) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    terminal = Terminal("r", "c", "e", edits=[rewrite_note])
    assert review_batch("gem01", root, terminal.io()).edited == 1
    item = staged(root)["gem01-01"]
    assert (item.note, item.review, item.provenance) == ("fixed by hand", "edited", "gemini-3-pro")
    assert not list((root / "staging" / "gem01").glob(".edit-*"))


def test_an_invalid_edit_is_shown_and_can_be_discarded(tmp_path: Path, root: Path) -> None:
    stage(tmp_path, root, two_span_draft("gem01-01"))
    terminal = Terminal("r", "c", "e", "d", "", edits=[break_quote])
    assert review_batch("gem01", root, terminal.io()).accepted == 1
    assert "quote is not in turn 0" in terminal.text
    assert staged(root)["gem01-01"].note == NOTE


def test_an_invalid_edit_can_be_edited_again(tmp_path: Path, root: Path) -> None:
    def fix(path: Path) -> None:  # the second edit starts from the broken file
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["expected"][0]["quote"] == "not in the turn"
        data["expected"][0]["quote"] = "Can you send the deck?"
        data["note"] = "fixed by hand"
        path.write_text(json.dumps(data), encoding="utf-8")

    stage(tmp_path, root, two_span_draft("gem01-01"))
    terminal = Terminal("r", "c", "e", "e", edits=[break_quote, fix])
    assert review_batch("gem01", root, terminal.io()).edited == 1
    assert staged(root)["gem01-01"].note == "fixed by hand"


def test_cli_review_of_a_missing_batch_exits_1(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["review", "--batch", "nope", "--sets-dir", str(root)]) == 1
    assert "no set named 'staging/nope'" in capsys.readouterr().err
