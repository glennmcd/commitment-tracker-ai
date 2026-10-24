"""Named evaluation sets: manifests, canonical hashes and the review rule."""

import json
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation.dataset import DatasetError, canonical_sha256
from commitment_tracker.evaluation.sets import (
    SETS_DIR,
    SetError,
    SetManifest,
    list_sets,
    load_set,
    set_dir,
)
from tests.eval.test_dataset import item_data


def manifest(set_name: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": set_name,
        "description": "A set for tests.",
        "role": "test",
        "gated": True,
        "sources": [],
    }
    data.update(overrides)
    return data


def write_set(
    root: Path, set_name: str, items: list[dict[str, Any]], **manifest_overrides: Any
) -> Path:
    directory = root / set_name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "set.json").write_text(
        json.dumps(manifest(set_name, **manifest_overrides)), encoding="utf-8"
    )
    (directory / "items.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
    )
    return directory


# --- canonical hash ------------------------------------------------------------------------------


def test_hash_ignores_key_order_spacing_and_line_endings(tmp_path: Path) -> None:
    data = item_data()
    plain = tmp_path / "a.jsonl"
    plain.write_text(json.dumps(data) + "\n", encoding="utf-8")
    shuffled = tmp_path / "b.jsonl"
    reordered = dict(reversed(list(data.items())))
    shuffled.write_bytes(
        (json.dumps(reordered, indent=None, separators=(" ,", " : ")) + "\r\n\r\n").encode()
    )
    assert canonical_sha256(plain) == canonical_sha256(shuffled)


def test_hash_changes_with_content(tmp_path: Path) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(json.dumps(item_data()) + "\n", encoding="utf-8")
    b.write_text(json.dumps(item_data(note="changed")) + "\n", encoding="utf-8")
    assert canonical_sha256(a) != canonical_sha256(b)


def test_hash_of_bad_json_names_the_line(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps(item_data()) + "\n{nope\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="line 2"):
        canonical_sha256(path)


# --- loading -------------------------------------------------------------------------------------


def test_load_set_returns_items_manifest_and_hash(tmp_path: Path) -> None:
    directory = write_set(tmp_path, "test", [item_data(), item_data(id="x-02")])
    loaded = load_set("test", tmp_path)
    assert loaded.name == "test"
    assert loaded.manifest.gated
    assert [item.id for item in loaded.items] == ["x-01", "x-02"]
    assert loaded.sha256 == canonical_sha256(directory / "items.jsonl")


def test_unreviewed_items_are_rejected_outside_staging(tmp_path: Path) -> None:
    write_set(tmp_path, "test", [item_data(review="unreviewed")])
    with pytest.raises(SetError, match="unreviewed items: x-01"):
        load_set("test", tmp_path)


def test_staging_sets_may_hold_unreviewed_items(tmp_path: Path) -> None:
    write_set(tmp_path, "staging/gem01", [item_data(review="unreviewed")], role="staging")
    assert load_set("staging/gem01", tmp_path).items[0].review == "unreviewed"


def test_manifest_name_must_match_the_directory(tmp_path: Path) -> None:
    write_set(tmp_path, "test", [item_data()], name="dev")
    with pytest.raises(SetError, match="names itself 'dev'"):
        load_set("test", tmp_path)


def test_manifest_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        SetManifest.model_validate(manifest("test", surprise=1))


@pytest.mark.parametrize("name", ["../etc", "Test", "staging/../dev", "a/b/c", ""])
def test_bad_set_names_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(SetError, match="set name"):
        set_dir(name, tmp_path)


def test_missing_set_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SetError, match="no set named 'test'"):
        load_set("test", tmp_path)


def test_list_sets_finds_top_level_and_staging(tmp_path: Path) -> None:
    write_set(tmp_path, "dev", [item_data()], role="dev", gated=False)
    write_set(tmp_path, "test", [item_data(id="t-01")])
    write_set(tmp_path, "staging/gem01", [item_data(id="g-01")], role="staging")
    assert list_sets(tmp_path) == ["dev", "staging/gem01", "test"]


# --- the committed sets --------------------------------------------------------------------------


def test_committed_dev_set_loads() -> None:
    dev = load_set("dev", SETS_DIR)
    assert dev.manifest.role == "dev"
    assert not dev.manifest.gated
    assert len(dev.items) >= 24


def test_committed_test_manifest_is_gated() -> None:
    test = SetManifest.model_validate_json((SETS_DIR / "test" / "set.json").read_text("utf-8"))
    assert test.role == "test"
    assert test.gated
