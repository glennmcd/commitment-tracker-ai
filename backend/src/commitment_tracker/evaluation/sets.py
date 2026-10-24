"""Named evaluation sets under backend/eval/sets/<name>/: a manifest and its items.

`set.json` records the set's role, whether the regression gate covers it, and the batches it was
built from; `items.jsonl` holds the items. A set is pinned by the canonical hash of its items.
Staging sets (`staging/<batch>`) hold imported drafts awaiting review; every other set holds only
reviewed items.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from commitment_tracker.evaluation.dataset import (
    DatasetError,
    EvalItem,
    canonical_sha256,
    load_dataset,
)

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


def load_set(name: str, root: Path = SETS_DIR) -> LoadedSet:
    """Load a text set: manifest, validated items and canonical hash."""
    manifest = load_manifest(name, root)
    if manifest.kind != "text":
        raise SetError(f"{name} is an {manifest.kind} set; it has no items of its own")
    path = set_dir(name, root) / "items.jsonl"
    try:
        items = load_dataset(path)
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
