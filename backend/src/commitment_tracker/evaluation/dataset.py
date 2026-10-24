"""Evaluation items: a transcript, its call date, and the spans a correct extractor returns.

One item per line of a JSONL file. Every expected span names its turn and a quote from that turn, so
predictions can be matched to it. Field accuracy is scored on ledger spans only: owner, action
keywords (all must appear in the predicted action) and the resolved due date. The other fields
document the expectation for readers.
"""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from commitment_tracker.schemas import LEDGER_LABELS, Label, Precision, Turn

# backend/src/commitment_tracker/evaluation/dataset.py -> backend/eval/sets/dev/items.jsonl
DEV_PATH = Path(__file__).resolve().parents[3] / "eval" / "sets" / "dev" / "items.jsonl"

Tag = Literal["ambiguous", "multi_turn", "keyword_trap"]
Review = Literal["unreviewed", "accepted", "edited"]
# Who wrote the item: the spec, a person, or a generator named `<family>-<model>`.
PROVENANCE = r"^(spec|hand-written|[a-z]+-[a-z0-9][a-z0-9.\-]*)$"


class DatasetError(ValueError):
    pass


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedSpan(EvalModel):
    turn_index: int = Field(ge=0)
    label: Label
    quote: str = Field(min_length=1, description="Text from the turn that identifies the span.")
    owner: str | None = None
    recipient: str | None = None
    action_keywords: list[str] = Field(default_factory=list)
    due_raw: str | None = None
    due_resolved: date | None = None
    precision: Precision = Precision.NONE
    condition: str | None = None

    @field_validator("action_keywords")
    @classmethod
    def _lower_case(cls, keywords: list[str]) -> list[str]:
        if any(keyword != keyword.lower() or not keyword.strip() for keyword in keywords):
            raise ValueError("action_keywords must be non-empty lower case words")
        return keywords

    @model_validator(mode="after")
    def _label_rules(self) -> Self:
        if self.label is Label.CONDITIONAL and not self.condition:
            raise ValueError("a CONDITIONAL span needs its condition")
        if self.label in LEDGER_LABELS and not self.owner:
            raise ValueError(f"a {self.label} span needs an owner")
        if self.due_resolved is not None and self.precision not in {Precision.DAY, Precision.WEEK}:
            raise ValueError("a resolved due date needs day or week precision")
        return self


class EvalItem(EvalModel):
    id: str = Field(min_length=1)
    call_date: date
    turns: list[Turn] = Field(min_length=1)
    tags: list[Tag] = Field(default_factory=list)
    expected: list[ExpectedSpan] = Field(min_length=1)
    note: str | None = None
    provenance: str = Field(pattern=PROVENANCE)
    review: Review

    @model_validator(mode="after")
    def _spans_point_into_the_transcript(self) -> Self:
        for span in self.expected:
            if span.turn_index >= len(self.turns):
                raise ValueError(
                    f"turn_index {span.turn_index} is outside the {len(self.turns)} turns"
                )
            if span.quote not in self.turns[span.turn_index].text:
                raise ValueError(f"quote is not in turn {span.turn_index}: {span.quote!r}")
        return self


def describe_validation_error(error: ValidationError) -> str:
    parts = []
    for detail in error.errors(include_url=False, include_input=False):
        path = ".".join(str(part) for part in detail["loc"])
        parts.append(f"{path}: {detail['msg']}" if path else detail["msg"])
    return "; ".join(parts)


def canonical_sha256(path: Path) -> str:
    """SHA-256 of a JSONL file's items in canonical form (sorted keys, compact, one per line), so
    key order, spacing, blank lines and line endings never change a set's hash."""
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as error:
            raise DatasetError(f"{path.name} line {number}: {error.msg}") from None
        lines.append(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def load_dataset(path: Path) -> list[EvalItem]:
    """Load and validate every item; the first problem raises with its line number."""
    items: list[EvalItem] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = EvalItem.model_validate_json(line)
        except ValidationError as error:
            raise DatasetError(
                f"{path.name} line {number}: {describe_validation_error(error)}"
            ) from None
        if item.id in seen:
            raise DatasetError(f"{path.name} line {number}: duplicate id {item.id}")
        seen.add(item.id)
        items.append(item)
    if not items:
        raise DatasetError(f"{path.name} has no items")
    return items
