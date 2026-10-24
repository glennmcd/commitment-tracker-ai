"""Leak checks: no transcript or id in two sets, no test text in a prompt, no Claude drafts in test.

The first test runs every check on the committed sets and prompts; the rest show each check catches
what it should on a throwaway tree.
"""

import json
from pathlib import Path

from commitment_tracker.evaluation.leaks import (
    all_leaks,
    claude_drafts_in_test,
    duplicate_ids,
    duplicate_transcripts,
    normalize,
    orphan_clips,
    prompt_leaks,
)
from tests.eval.test_dataset import item_data
from tests.eval.test_set_loading import write_set

LONG_TURN = "We will ship the revised contract to legal next Tuesday."


def turns(text: str) -> list[dict[str, str]]:
    return [{"speaker": "seller", "text": text}]


def none_item(item_id: str, text: str, **overrides: object) -> dict[str, object]:
    expected = [{"turn_index": 0, "label": "NONE", "quote": text}]
    return item_data(id=item_id, turns=turns(text), expected=expected, **overrides)


def test_committed_sets_do_not_leak() -> None:
    assert all_leaks() == []


def test_normalize_ignores_case_spacing_and_punctuation() -> None:
    assert normalize("  I'll  SEND it,\nFriday! ") == normalize("i ll send it friday")


def test_the_same_transcript_in_two_sets_is_found(tmp_path: Path) -> None:
    write_set(tmp_path, "dev", [none_item("d-1", "Our SLA is four hours.")], role="dev")
    write_set(tmp_path, "test", [none_item("t-1", "our sla is FOUR hours")])
    (problem,) = duplicate_transcripts(tmp_path)
    assert "dev:d-1" in problem and "test:t-1" in problem


def test_repeats_inside_one_set_are_not_a_leak(tmp_path: Path) -> None:
    items = [none_item("t-1", "Our SLA is four hours."), none_item("t-2", "Our SLA is four hours.")]
    write_set(tmp_path, "test", items)
    assert duplicate_transcripts(tmp_path) == []


def test_an_id_in_two_sets_is_found(tmp_path: Path) -> None:
    write_set(tmp_path, "dev", [none_item("x-1", "First text here.")], role="dev")
    write_set(tmp_path, "test", [none_item("x-1", "Second text here.")])
    assert duplicate_ids(tmp_path) == ["id x-1 is in dev, test"]


def test_a_test_turn_quoted_in_a_prompt_is_found(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "v9.md").write_text(f'Example: "{LONG_TURN.upper()}"\n', encoding="utf-8")
    write_set(tmp_path / "sets", "test", [none_item("t-1", LONG_TURN)])
    assert prompt_leaks(tmp_path / "sets", prompts) == [
        "test:t-1 turn 0 is quoted in prompts/v9.md"
    ]


def test_short_turns_and_dev_items_may_appear_in_prompts(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "v9.md").write_text(f"Will do. {LONG_TURN}\n", encoding="utf-8")
    write_set(tmp_path / "sets", "dev", [none_item("d-1", LONG_TURN)], role="dev")
    write_set(tmp_path / "sets", "test", [none_item("t-1", "Will do.")])
    assert prompt_leaks(tmp_path / "sets", prompts) == []


def test_claude_drafts_are_found_only_in_test_sets(tmp_path: Path) -> None:
    claude = {"provenance": "claude-opus-5-5"}
    write_set(tmp_path, "dev", [none_item("d-1", "Dev text.", **claude)], role="dev")
    write_set(tmp_path, "test", [none_item("t-1", "Test text.", **claude)])
    assert claude_drafts_in_test(tmp_path) == ["test:t-1 has provenance claude-opus-5-5"]


def test_audio_clips_must_point_at_items_of_their_source_set(tmp_path: Path) -> None:
    write_set(tmp_path, "test", [none_item("t-1", "Test text.")])
    audio = tmp_path / "audio"
    audio.mkdir()
    manifest = {"name": "audio", "role": "test", "kind": "audio", "items_from": "test"}
    (audio / "set.json").write_text(json.dumps(manifest), encoding="utf-8")
    clips = [{"test_item_id": "t-1"}, {"test_item_id": "t-9"}]
    (audio / "clips.jsonl").write_text("".join(json.dumps(c) + "\n" for c in clips), "utf-8")
    assert orphan_clips(tmp_path) == ["audio clip points at 't-9', which test lacks"]
