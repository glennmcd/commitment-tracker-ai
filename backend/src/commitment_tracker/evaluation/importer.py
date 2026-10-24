"""`uv run eval import`: turn a generator's JSONL reply into a staging batch awaiting review.

    uv run eval import gemini.jsonl --batch gem01 --provenance gemini-3-pro

1. Markdown fences and blank lines are skipped; every other line is validated with the dataset
   rules, and every rejection is collected with its line number (the import never stops early).
2. Exact duplicates of an item in any set (normalised transcript), and ids already used, are
   rejected; near duplicates (difflib ratio >= 0.85) are kept but flagged for review.
3. Every span with a `due_raw` is re-resolved with the extractor's resolver; disagreements are
   recorded for review and the item keeps the generator's date.
4. Accepted lines go to eval/sets/staging/<batch>/items.jsonl as `unreviewed`, with the manifest and
   `import.json` (rejections, date disagreements, near duplicates) beside them.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel, ValidationError

from commitment_tracker.evaluation.dataset import (
    PROVENANCE,
    EvalItem,
    describe_validation_error,
)
from commitment_tracker.evaluation.leaks import transcript_key
from commitment_tracker.evaluation.sets import (
    SETS_DIR,
    STAGING,
    SetManifest,
    SetSource,
    list_sets,
    load_manifest,
    load_set,
    set_dir,
)
from commitment_tracker.extractor.dates import resolve_due

# backend/src/commitment_tracker/evaluation/importer.py -> backend/eval/generation
GENERATION_DIR = Path(__file__).resolve().parents[3] / "eval" / "generation"
GENERATION_PROMPT = re.compile(r"prompt-v([0-9]+)")
BATCH = re.compile(r"[a-z0-9][a-z0-9-]*")
NEAR_DUPLICATE = 0.85
HAND_WRITTEN = "hand-written"


class BatchError(ValueError):
    pass


class Rejection(BaseModel):
    line: int
    reason: str


class DateDisagreement(BaseModel):
    item: str
    span: int
    generator: date | None
    resolver: date | None


class NearDuplicate(BaseModel):
    item: str
    of: str  # "<set>:<id>" or "<batch>:<id>" for an earlier line of the same batch
    ratio: float


class ImportReport(BaseModel):
    batch: str
    source: str  # the file name only
    provenance: str
    generation_prompt: str | None
    imported_on: date
    imported: int
    rejections: list[Rejection]
    date_disagreements: list[DateDisagreement]
    near_duplicates: list[NearDuplicate]


@dataclass(frozen=True)
class ImportResult:
    directory: Path
    imported: list[str]
    rejections: list[Rejection]
    date_disagreements: list[DateDisagreement]
    near_duplicates: list[NearDuplicate]


def latest_generation_prompt(directory: Path = GENERATION_DIR) -> str:
    versions = [
        int(match.group(1))
        for path in directory.glob("prompt-v*.md")
        if (match := GENERATION_PROMPT.fullmatch(path.stem))
    ]
    if not versions:
        raise BatchError(f"no generation prompt in {directory}")
    return f"prompt-v{max(versions)}"


def _existing(root: Path) -> tuple[dict[str, str], set[str]]:
    """Normalised transcripts (to "<set>:<id>") and ids across every text set."""
    transcripts: dict[str, str] = {}
    ids: set[str] = set()
    for name in list_sets(root):
        if load_manifest(name, root).kind != "text":
            continue
        for item in load_set(name, root, allow_empty=True).items:
            transcripts.setdefault(transcript_key(item), f"{name}:{item.id}")
            ids.add(item.id)
    return transcripts, ids


def _date_checks(item: EvalItem) -> list[DateDisagreement]:
    found = []
    for index, span in enumerate(item.expected):
        if span.due_raw is None:
            continue
        resolved = resolve_due(span.due_raw, item.call_date).resolved
        if resolved != span.due_resolved:
            found.append(
                DateDisagreement(
                    item=item.id, span=index, generator=span.due_resolved, resolver=resolved
                )
            )
    return found


def _check_options(batch: str, provenance: str, root: Path) -> Path:
    if not BATCH.fullmatch(batch):
        raise BatchError(f"batch must be lower-case letters, digits and dashes, not {batch!r}")
    if not re.fullmatch(PROVENANCE, provenance) or provenance == "spec":
        raise BatchError(
            f"provenance must be hand-written or <family>-<model>, not {provenance!r}"
            + (" (spec is reserved for the spec's seed items)" if provenance == "spec" else "")
        )
    directory = set_dir(f"{STAGING}/{batch}", root)
    if directory.exists():
        raise BatchError(f"batch {batch} already exists at {directory}")
    return directory


def import_batch(
    source: Path,
    *,
    batch: str,
    provenance: str,
    generation_prompt: str | None,
    root: Path = SETS_DIR,
    today: date,
) -> ImportResult:
    directory = _check_options(batch, provenance, root)
    prompt = None if provenance == HAND_WRITTEN else generation_prompt
    transcripts, ids = _existing(root)

    accepted: list[tuple[EvalItem, str]] = []  # item and its normalised transcript
    rejections: list[Rejection] = []
    near: list[NearDuplicate] = []
    for number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as error:
            rejections.append(Rejection(line=number, reason=f"invalid JSON: {error.msg}"))
            continue
        if not isinstance(data, dict):
            rejections.append(Rejection(line=number, reason="not a JSON object"))
            continue
        try:
            item = EvalItem.model_validate(
                {**data, "provenance": provenance, "review": "unreviewed"}
            )
        except ValidationError as error:
            rejections.append(Rejection(line=number, reason=describe_validation_error(error)))
            continue
        key = transcript_key(item)
        if item.id in ids:
            rejections.append(Rejection(line=number, reason=f"duplicate id {item.id}"))
            continue
        if key in transcripts:
            reason = f"same transcript as {transcripts[key]}"
            rejections.append(Rejection(line=number, reason=reason))
            continue
        best = max(
            (
                (SequenceMatcher(None, key, other).ratio(), where)
                for other, where in transcripts.items()
            ),
            default=(0.0, ""),
        )
        if best[0] >= NEAR_DUPLICATE:
            near.append(NearDuplicate(item=item.id, of=best[1], ratio=round(best[0], 3)))
        ids.add(item.id)
        transcripts[key] = f"{batch}:{item.id}"
        accepted.append((item, key))

    if not accepted:  # nothing is written; the caller reports the rejections
        return ImportResult(directory, [], rejections, [], near)

    items = [item for item, _ in accepted]
    disagreements = [d for item in items for d in _date_checks(item)]
    call_dates = {item.call_date for item in items}
    manifest = SetManifest(
        name=f"{STAGING}/{batch}",
        description=f"Imported from {source.name}; awaiting blind review.",
        role="staging",
        gated=False,
        sources=[
            SetSource(
                batch=batch,
                provenance=provenance,
                generation_prompt=prompt,
                call_date=call_dates.pop() if len(call_dates) == 1 else None,
                imported=today,
                items=len(items),
            )
        ],
    )
    report = ImportReport(
        batch=batch,
        source=source.name,
        provenance=provenance,
        generation_prompt=prompt,
        imported_on=today,
        imported=len(items),
        rejections=rejections,
        date_disagreements=disagreements,
        near_duplicates=near,
    )
    directory.mkdir(parents=True)
    write_items(directory / "items.jsonl", items)
    write_json(directory / "set.json", manifest)
    write_json(directory / "import.json", report)
    return ImportResult(
        directory=directory,
        imported=[item.id for item in items],
        rejections=rejections,
        date_disagreements=disagreements,
        near_duplicates=near,
    )


def item_line(item: EvalItem) -> str:
    """One item as a JSONL line; turn timestamps appear only when set (audio items)."""
    data = item.model_dump(mode="json")
    for turn in data["turns"]:
        for key in ("start_ms", "end_ms"):
            if turn[key] is None:
                del turn[key]
    return json.dumps(data, ensure_ascii=False)


def write_items(path: Path, items: list[EvalItem]) -> None:
    """One item per line, LF endings on every platform, so set hashes and diffs stay stable."""
    lines = [item_line(item) for item in items]
    path.write_bytes(("\n".join(lines) + "\n" if lines else "").encode("utf-8"))


def append_items(path: Path, items: list[EvalItem]) -> None:
    """Add items after the existing lines, leaving those byte for byte as they are."""
    existing = path.read_bytes() if path.is_file() else b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    added = "".join(item_line(item) + "\n" for item in items)
    path.write_bytes(existing + added.encode("utf-8"))


def write_json(path: Path, model: BaseModel) -> None:
    path.write_bytes((model.model_dump_json(indent=2) + "\n").encode("utf-8"))
