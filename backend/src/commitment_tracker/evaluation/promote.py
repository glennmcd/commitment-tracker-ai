"""`uv run eval promote --batch <name> --to <set>`: move reviewed items out of staging.

Accepted and edited items are appended to the target set and the batch is added to its manifest's
sources; rejected items and the review log stay in staging. Every item must have been decided
first. Claude-drafted items never enter a test set. Promoting into a gated set changes its hash,
so the regression gate then wants a new report and baseline.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from commitment_tracker.evaluation.importer import append_items, write_items, write_json
from commitment_tracker.evaluation.leaks import CLAUDE_PROVENANCE
from commitment_tracker.evaluation.review import load_reviews
from commitment_tracker.evaluation.sets import (
    SETS_DIR,
    STAGING,
    is_staging,
    load_set,
    set_dir,
)


class PromoteError(ValueError):
    pass


@dataclass(frozen=True)
class PromoteResult:
    target: str
    promoted: list[str]
    sha256: str  # the target set's new hash
    gated: bool


def promote_batch(batch: str, target: str, root: Path = SETS_DIR, *, today: date) -> PromoteResult:
    if is_staging(target):
        raise PromoteError(f"promote into a dev or test set, not the staging set {target}")
    staging_name = f"{STAGING}/{batch}"
    staging = load_set(staging_name, root, allow_empty=True)
    destination = load_set(target, root, allow_empty=True)
    if destination.manifest.kind != "text":
        raise PromoteError(f"{target} is an {destination.manifest.kind} set")

    decided = {record.item for record in load_reviews(set_dir(staging_name, root))}
    undecided = [item.id for item in staging.items if item.id not in decided]
    if undecided:
        raise PromoteError(
            f"{len(undecided)} items are not reviewed yet; run uv run eval review --batch {batch}"
        )
    moving = [item for item in staging.items if item.review in {"accepted", "edited"}]
    if not moving:
        raise PromoteError(f"nothing to promote from {staging_name}")
    if destination.manifest.role == "test":
        claude = [item.id for item in moving if item.provenance.startswith(CLAUDE_PROVENANCE)]
        if claude:
            raise PromoteError(
                f"Claude-drafted items can't enter the test set {target}: {', '.join(claude)}"
            )
    existing = {item.id for item in destination.items}
    clashes = [item.id for item in moving if item.id in existing]
    if clashes:
        raise PromoteError(f"{target} already has {', '.join(clashes)}")

    if len(staging.manifest.sources) != 1:
        raise PromoteError(f"{staging_name}/set.json must record exactly one source batch")
    source = staging.manifest.sources[0]
    manifest = destination.manifest.model_copy(
        update={
            "sources": [
                *destination.manifest.sources,
                source.model_copy(update={"promoted": today, "items": len(moving)}),
            ]
        }
    )
    staying = [item for item in staging.items if item not in moving]
    target_dir = set_dir(target, root)
    append_items(target_dir / "items.jsonl", moving)
    write_json(target_dir / "set.json", manifest)
    write_items(set_dir(staging_name, root) / "items.jsonl", staying)
    return PromoteResult(
        target=target,
        promoted=[item.id for item in moving],
        sha256=load_set(target, root).sha256,
        gated=manifest.gated,
    )
