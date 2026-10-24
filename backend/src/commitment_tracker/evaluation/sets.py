"""Named evaluation sets under backend/eval/sets/<name>/: a manifest and its items.

`set.json` records the set's role, whether the regression gate covers it, and the batches it was
built from; `items.jsonl` holds the items. A set is pinned by the canonical hash of its items.
Staging sets (`staging/<batch>`) hold imported drafts awaiting review; every other set holds only
reviewed items.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from commitment_tracker.evaluation.dataset import (
    DatasetError,
    EvalItem,
    canonical_sha256,
    jsonl_lines,
    load_dataset,
)
from commitment_tracker.schemas import Label

# backend/src/commitment_tracker/evaluation/sets.py -> backend/eval/sets
SETS_DIR = Path(__file__).resolve().parents[3] / "eval" / "sets"
SET_NAME = re.compile(r"[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)?")
STAGING = "staging"


class SetError(ValueError):
    pass


class SetSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    generation_prompt: str | None = None
    call_date: date | None = None
    imported: date | None = None
    promoted: date | None = None
    items: int = Field(ge=0)


class SetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    role: Literal["dev", "test", "staging"]
    gated: bool = False
    kind: Literal["text", "audio"] = "text"
    items_from: str | None = None  # audio sets point at the text set their clips come from
    sources: list[SetSource] = Field(default_factory=list)


@dataclass(frozen=True)
class LoadedSet:
    name: str
    manifest: SetManifest
    items: list[EvalItem]
    sha256: str

    @property
    def staging(self) -> bool:
        return is_staging(self.name)


def is_staging(name: str) -> bool:
    return name.split("/")[0] == STAGING


def set_dir(name: str, root: Path = SETS_DIR) -> Path:
    if not SET_NAME.fullmatch(name):
        raise SetError(f"set name must look like 'test' or 'staging/gem01', not {name!r}")
    return root / name


def load_manifest(name: str, root: Path = SETS_DIR) -> SetManifest:
    path = set_dir(name, root) / "set.json"
    if not path.is_file():
        raise SetError(f"no set named {name!r} (looked for {path})")
    try:
        manifest = SetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise SetError(f"{name}/set.json: {error.errors(include_url=False)[0]['msg']}") from None
    if manifest.name != name:
        raise SetError(f"{name}/set.json names itself {manifest.name!r}")
    return manifest


def load_set(name: str, root: Path = SETS_DIR, *, allow_empty: bool = False) -> LoadedSet:
    """Load a text set: manifest, validated items and canonical hash. An empty set loads only with
    `allow_empty` (for listing and promoting); a run needs items."""
    manifest = load_manifest(name, root)
    if manifest.kind != "text":
        raise SetError(f"{name} is an {manifest.kind} set; it has no items of its own")
    path = set_dir(name, root) / "items.jsonl"
    try:
        empty = allow_empty and not path.read_text(encoding="utf-8").strip()
        items = [] if empty else load_dataset(path)
        sha256 = canonical_sha256(path)
    except (DatasetError, FileNotFoundError) as error:
        raise SetError(f"{name}: {error}") from None
    if not is_staging(name):
        unreviewed = [item.id for item in items if item.review == "unreviewed"]
        if unreviewed:
            raise SetError(f"{name} holds unreviewed items: {', '.join(unreviewed)}")
    return LoadedSet(name=name, manifest=manifest, items=items, sha256=sha256)


def list_sets(root: Path = SETS_DIR) -> list[str]:
    """Every set with a manifest, top-level and staging, sorted by name."""
    names = [path.parent.relative_to(root).as_posix() for path in root.glob("*/set.json")] + [
        path.parent.relative_to(root).as_posix() for path in root.glob(f"{STAGING}/*/set.json")
    ]
    return sorted(names)


# --- `uv run eval-sets` --------------------------------------------------------------------------


@dataclass(frozen=True)
class SetSummary:
    name: str
    role: str
    gated: bool
    items: int = 0
    sha256: str = ""
    review: dict[str, int] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)  # by expected span, in label order
    provenance: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def summarize(root: Path = SETS_DIR) -> list[SetSummary]:
    """One summary per set; a set that fails to load is reported with its error."""
    summaries = []
    for name in list_sets(root):
        try:
            manifest = load_manifest(name, root)
        except SetError as error:
            summaries.append(SetSummary(name, role="?", gated=False, error=str(error)))
            continue
        if manifest.kind == "audio":
            summaries.append(_audio_summary(name, manifest, set_dir(name, root) / "clips.jsonl"))
            continue
        try:
            loaded = load_set(name, root, allow_empty=True)
        except SetError as error:
            summaries.append(SetSummary(name, manifest.role, manifest.gated, error=str(error)))
            continue
        labels = Counter(span.label for item in loaded.items for span in item.expected)
        summaries.append(
            SetSummary(
                name=name,
                role=manifest.role,
                gated=manifest.gated,
                items=len(loaded.items),
                sha256=loaded.sha256,
                review=dict(sorted(Counter(item.review for item in loaded.items).items())),
                labels={label.value: labels[label] for label in Label if labels[label]},
                provenance=dict(sorted(Counter(item.provenance for item in loaded.items).items())),
            )
        )
    return summaries


def _audio_summary(name: str, manifest: SetManifest, clips: Path) -> SetSummary:
    """An audio set holds clips, not items: count them by source (polly or human)."""
    try:
        lines = [line for line in jsonl_lines(clips) if line.strip()]
        sources = Counter(json.loads(line)["source"] for line in lines)
        sha256 = canonical_sha256(clips)
    except (OSError, ValueError, KeyError, DatasetError) as error:
        return SetSummary(name, manifest.role, manifest.gated, error=f"clips.jsonl: {error}")
    return SetSummary(
        name=name,
        role=manifest.role,
        gated=manifest.gated,
        items=len(lines),
        sha256=sha256,
        provenance=dict(sorted(sources.items())),
    )


def _mix(counts: dict[str, int]) -> str:
    return ", ".join(f"{key} {count}" for key, count in counts.items()) or "-"


def render_summary(summary: SetSummary) -> list[str]:
    head = f"{summary.name}  role {summary.role}  gated {'yes' if summary.gated else 'no'}"
    if summary.error is not None:
        return [head, f"  error       {summary.error}"]
    return [
        f"{head}  items {summary.items}  sha256 {summary.sha256[:12]}",
        f"  review      {_mix(summary.review)}",
        f"  labels      {_mix(summary.labels)}",
        f"  provenance  {_mix(summary.provenance)}",
    ]
