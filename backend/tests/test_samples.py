"""The sample-clip catalog and the manifest bundled with the package."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from commitment_tracker.jobs.samples import SampleCatalog, SampleClip, load_catalog

SHA = "a" * 64


def clip(clip_id: str = "invoice", **changes: Any) -> SampleClip:
    fields: dict[str, Any] = {
        "id": clip_id,
        "title": "Resending an invoice",
        "duration_ms": 41_500,
        "sha256": SHA,
    }
    return SampleClip(**(fields | changes))


def test_a_clip_lives_under_samples_in_the_bucket() -> None:
    assert clip("invoice").key == "samples/invoice.wav"


def test_the_catalog_finds_clips_by_id_and_keeps_order() -> None:
    first, second = clip("one"), clip("two")
    catalog = SampleCatalog([first, second])
    assert catalog.get("two") == second
    assert catalog.get("missing") is None
    assert catalog.all() == [first, second]


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        SampleCatalog([clip("same"), clip("same")])


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "../escape"},
        {"id": "Upper"},
        {"id": ""},
        {"sha256": "xyz"},
        {"duration_ms": 0},
        {"duration_ms": 60_001},
        {"title": ""},
    ],
)
def test_invalid_clips_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        clip(**changes)


def test_load_catalog_reads_a_manifest_file(tmp_path: Path) -> None:
    path = tmp_path / "samples.json"
    path.write_text(json.dumps([clip("one").model_dump()]), encoding="utf-8")
    assert [c.id for c in load_catalog(path).all()] == ["one"]


def test_the_bundled_manifest_parses() -> None:
    load_catalog()
