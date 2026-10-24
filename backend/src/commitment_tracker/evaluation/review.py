"""`uv run eval review --batch <name>`: blind review of a staging batch in the terminal.

For each item the reviewer sees the call date and transcript, then each expected span's turn and
quote, and types a label before seeing the generator's. Agreement accepts on enter; a disagreement
shows both labels and the generator's note, and the reviewer keeps the generator's label, takes
their own (the item becomes `edited`) or rejects the item. Import's date disagreements are settled
the same way. `e` opens the item in $EDITOR and re-validates it. Provenance is shown only once the
item is decided.

Each decision is saved at once, to items.jsonl (labels, dates, review state) and review.jsonl (one
line per item: both labels per span, date verdicts, timestamps), so quitting loses nothing and a
rerun resumes with the undecided items. Rejected items stay `unreviewed` and are never promoted.
Transcripts are printed, since reading them is the point, but never logged.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from commitment_tracker.evaluation.dataset import EvalItem, ExpectedSpan, describe_validation_error
from commitment_tracker.evaluation.importer import write_items
from commitment_tracker.evaluation.sets import SETS_DIR, STAGING, load_set, set_dir
from commitment_tracker.extractor.dates import resolve_due
from commitment_tracker.extractor.prompt import DAY_NAMES
from commitment_tracker.schemas import Label

LABEL_KEYS = {
    "c": Label.COMMITMENT,
    "h": Label.HEDGED,
    "d": Label.CONDITIONAL,
    "s": Label.SUGGESTION,
    "r": Label.REQUEST,
    "p": Label.REPORTED,
    "x": Label.REFUSAL,
    "n": Label.NONE,
}
LABEL_PROMPT = (
    "c commitment  h hedged  d conditional  s suggestion  r request  p reported  x refusal  n none"
)
Outcome = Literal["accepted", "edited", "rejected"]


class SpanReview(BaseModel):
    span: int
    mine: Label
    generator: Label
    final: Label | None  # None when the item was rewritten in the editor


class DateReview(BaseModel):
    span: int
    generator: date | None
    resolver: date | None
    verdict: Literal["generator", "resolver"] | None  # None when settled in the editor


class ItemReview(BaseModel):
    item: str
    outcome: Outcome
    spans: list[SpanReview]
    dates: list[DateReview]
    shown_at: datetime
    decided_at: datetime


def _run_editor(path: Path) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        editor = "notepad" if sys.platform == "win32" else "vi"
    subprocess.run([editor, str(path)], check=False)  # no shell: the path is never interpreted


@dataclass(frozen=True)
class ReviewIO:
    input: Callable[[str], str] = input
    print: Callable[[str], None] = print
    edit: Callable[[Path], None] = _run_editor
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ReviewSummary:
    accepted: int = 0
    edited: int = 0
    rejected: int = 0
    remaining: int = 0


class _Quit(Exception):
    pass


def load_reviews(directory: Path) -> list[ItemReview]:
    path = directory / "review.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ItemReview.model_validate_json(line) for line in lines if line.strip()]


def _append_review(directory: Path, record: ItemReview) -> None:
    with (directory / "review.jsonl").open("ab") as out:
        out.write((record.model_dump_json() + "\n").encode("utf-8"))


class _Session:
    def __init__(self, directory: Path, io: ReviewIO) -> None:
        self.directory = directory
        self.io = io

    def ask(self, prompt: str, keys: set[str]) -> str:
        while True:
            answer = self.io.input(prompt).strip().lower()
            if answer == "q":
                raise _Quit
            if answer in keys:
                return answer
            self.io.print(f"unknown key {answer!r}")

    def show(self, item: EvalItem, position: int, total: int) -> None:
        day = item.call_date
        self.io.print("")
        self.io.print(
            f"item {position} of {total} | {item.id} | call date {day} ({DAY_NAMES[day.weekday()]})"
        )
        for index, turn in enumerate(item.turns):
            self.io.print(f"  [{index}] {turn.speaker}: {turn.text}")

    def blind_labels(self, item: EvalItem) -> list[Label]:
        mine = []
        for index, span in enumerate(item.expected):
            self.io.print(f'span {index}, turn {span.turn_index}: "{span.quote}"')
            key = self.ask(f"  your label ({LABEL_PROMPT}, q quit): ", set(LABEL_KEYS))
            mine.append(LABEL_KEYS[key])
        return mine

    def edit(self, item: EvalItem) -> EvalItem | None:
        """Open the item in the editor until it validates; None when the edit is discarded."""
        path = self.directory / f".edit-{item.id}.json"
        editable = item.model_dump(mode="json", exclude={"provenance", "review"})
        path.write_bytes(
            (json.dumps(editable, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )
        try:
            while True:
                self.io.edit(path)
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return EvalItem.model_validate(
                        {**data, "provenance": item.provenance, "review": "edited"}
                    )
                except json.JSONDecodeError as error:
                    self.io.print(f"not valid JSON: {error.msg}")
                except ValidationError as error:
                    self.io.print(f"not a valid item: {describe_validation_error(error)}")
                if self.ask("  [e] edit again  [d] discard the edit: ", {"e", "d"}) == "d":
                    return None
        finally:
            path.unlink(missing_ok=True)

    def review(self, item: EvalItem, position: int, total: int) -> tuple[ItemReview, EvalItem]:
        shown_at = self.io.now()
        self.show(item, position, total)
        mine = self.blind_labels(item)
        spans = [
            SpanReview(span=i, mine=m, generator=s.label, final=s.label)
            for i, (m, s) in enumerate(zip(mine, item.expected, strict=True))
        ]
        dates = [
            DateReview(span=i, generator=s.due_resolved, resolver=resolved, verdict=None)
            for i, s in enumerate(item.expected)
            if s.due_raw is not None
            and (resolved := resolve_due(s.due_raw, item.call_date).resolved) != s.due_resolved
        ]
        current = item
        changed = False

        def finish(outcome: Outcome, final: EvalItem) -> tuple[ItemReview, EvalItem]:
            record = ItemReview(
                item=item.id,
                outcome=outcome,
                spans=spans,
                dates=dates,
                shown_at=shown_at,
                decided_at=self.io.now(),
            )
            return record, final

        def edited_in_editor() -> tuple[ItemReview, EvalItem] | None:
            rewritten = self.edit(current)
            if rewritten is None:
                return None
            for span in spans:
                span.final = None
            return finish("edited", rewritten)

        for review in spans:
            if review.mine == review.generator:
                continue
            self.io.print(
                f"span {review.span}: you said {review.mine}, the generator said "
                f"{review.generator}. Note: {item.note or '-'}"
            )
            while True:
                key = self.ask(
                    "  [g] keep the generator's  [m] take mine  [e] edit  [r] reject  [q] quit: ",
                    {"g", "m", "e", "r"},
                )
                if key == "e":
                    if (result := edited_in_editor()) is not None:
                        return result
                    continue
                break
            if key == "r":
                return finish("rejected", item)
            if key == "m":
                current = _relabel(current, review.span, review.mine)
                review.final = review.mine
                changed = True

        for check in dates:
            span = current.expected[check.span]
            self.io.print(
                f"span {check.span} due {span.due_raw!r}: the generator says "
                f"{check.generator or '-'}, the resolver says {check.resolver or '-'}"
            )
            while True:
                key = self.ask(
                    "  [g] generator is right  [v] resolver is right  [e] edit  [r] reject  "
                    "[q] quit: ",
                    {"g", "v", "e", "r"},
                )
                if key == "e":
                    if (result := edited_in_editor()) is not None:
                        return result
                    continue
                break
            if key == "r":
                return finish("rejected", item)
            if key == "g":
                check.verdict = "generator"
                self.io.print(
                    "  if the resolver is wrong, add a failing case to tests/test_dates.py"
                )
            else:
                check.verdict = "resolver"
                current = _redate(current, check.span)
                changed = True

        disagreed = bool(dates) or any(s.mine != s.generator for s in spans)
        if not disagreed:
            while True:
                key = self.ask(
                    "  labels agree. [enter] accept  [e] edit  [r] reject  [q] quit: ",
                    {"", "e", "r"},
                )
                if key == "e":
                    if (result := edited_in_editor()) is not None:
                        return result
                    continue
                break
            if key == "r":
                return finish("rejected", item)
        if changed:
            return finish("edited", current.model_copy(update={"review": "edited"}))
        return finish("accepted", current.model_copy(update={"review": "accepted"}))


def _replace_span(item: EvalItem, index: int, span: ExpectedSpan) -> EvalItem:
    expected = list(item.expected)
    expected[index] = span
    return EvalItem.model_validate(
        {**item.model_dump(), "expected": [s.model_dump() for s in expected]}
    )


def _relabel(item: EvalItem, index: int, label: Label) -> EvalItem:
    span = item.expected[index]
    data = {**span.model_dump(), "label": label}
    return _replace_span(item, index, ExpectedSpan.model_validate(data))


def _redate(item: EvalItem, index: int) -> EvalItem:
    span = item.expected[index]
    resolved = resolve_due(span.due_raw, item.call_date)
    data = {**span.model_dump(), "due_resolved": resolved.resolved, "precision": resolved.precision}
    return _replace_span(item, index, ExpectedSpan.model_validate(data))


def review_batch(batch: str, root: Path = SETS_DIR, io: ReviewIO | None = None) -> ReviewSummary:
    io = io or ReviewIO()
    name = f"{STAGING}/{batch}"
    directory = set_dir(name, root)
    items = load_set(name, root).items
    decided = {record.item for record in load_reviews(directory)}
    pending = [item for item in items if item.id not in decided]
    session = _Session(directory, io)
    counts = {"accepted": 0, "edited": 0, "rejected": 0}
    by_id = {item.id: item for item in items}
    for position, item in enumerate(pending, start=1):
        try:
            record, final = session.review(item, position, len(pending))
        except _Quit:
            break
        by_id[item.id] = final
        write_items(directory / "items.jsonl", list(by_id.values()))
        _append_review(directory, record)
        counts[record.outcome] += 1
        io.print(f"decided: {record.outcome} | provenance {item.provenance}")
    done = sum(counts.values())
    return ReviewSummary(**counts, remaining=len(pending) - done)
