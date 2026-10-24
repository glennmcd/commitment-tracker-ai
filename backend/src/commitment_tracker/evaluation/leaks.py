"""Checks that keep evaluation sets independent of each other and of the prompts.

Each check returns a list of problems (empty when clean), naming item ids, never transcript text:

- the same transcript in two sets, compared after normalising case, whitespace and punctuation;
- a turn of a non-dev item, six or more words long, quoted in a prompt file (shorter turns, like
  "Will do.", would match every prompt);
- an id used in two sets, or an audio clip pointing at an id its source set doesn't have;
- a Claude-drafted item in a test set (the extractor is Claude, so its drafts flatter the score).
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.sets import SETS_DIR, list_sets, load_manifest, load_set, set_dir

# backend/src/commitment_tracker/evaluation/leaks.py -> extractor/prompts
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "extractor" / "prompts"
MIN_PROMPT_LEAK_WORDS = 6
CLAUDE_PROVENANCE = "claude-"

_NOT_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    return " ".join(_NOT_WORD.sub(" ", text.lower()).split())


def transcript_key(item: EvalItem) -> str:
    return normalize(" ".join(turn.text for turn in item.turns))


def _text_sets(root: Path) -> dict[str, list[EvalItem]]:
    sets: dict[str, list[EvalItem]] = {}
    for name in list_sets(root):
        if load_manifest(name, root).kind == "text":
            sets[name] = load_set(name, root, allow_empty=True).items
    return sets


def duplicate_transcripts(root: Path = SETS_DIR) -> list[str]:
    seen: dict[str, list[str]] = defaultdict(list)
    for name, items in _text_sets(root).items():
        for item in items:
            seen[transcript_key(item)].append(f"{name}:{item.id}")
    return [
        f"same transcript in {', '.join(places)}"
        for places in seen.values()
        if len({place.split(":")[0] for place in places}) > 1
    ]


def duplicate_ids(root: Path = SETS_DIR) -> list[str]:
    owners: dict[str, list[str]] = defaultdict(list)
    for name, items in _text_sets(root).items():
        for item in items:
            owners[item.id].append(name)
    return [
        f"id {item_id} is in {', '.join(names)}"
        for item_id, names in owners.items()
        if len(names) > 1
    ]


def prompt_leaks(root: Path = SETS_DIR, prompts_dir: Path = PROMPTS_DIR) -> list[str]:
    prompts = {
        path.name: normalize(path.read_text(encoding="utf-8")) for path in prompts_dir.glob("*")
    }
    problems = []
    for name, items in _text_sets(root).items():
        if load_manifest(name, root).role == "dev":
            continue
        for item in items:
            for index, turn in enumerate(item.turns):
                text = normalize(turn.text)
                if len(text.split()) < MIN_PROMPT_LEAK_WORDS:
                    continue
                problems += [
                    f"{name}:{item.id} turn {index} is quoted in prompts/{prompt}"
                    for prompt, body in prompts.items()
                    if text in body
                ]
    return problems


def claude_drafts_in_test(root: Path = SETS_DIR) -> list[str]:
    return [
        f"{name}:{item.id} has provenance {item.provenance}"
        for name, items in _text_sets(root).items()
        if load_manifest(name, root).role == "test"
        for item in items
        if item.provenance.startswith(CLAUDE_PROVENANCE)
    ]


def orphan_clips(root: Path = SETS_DIR) -> list[str]:
    problems = []
    text_sets = _text_sets(root)
    for name in list_sets(root):
        manifest = load_manifest(name, root)
        if manifest.kind != "audio":
            continue
        source = manifest.items_from or ""
        ids = {item.id for item in text_sets.get(source, [])}
        clips = set_dir(name, root) / "clips.jsonl"
        lines = clips.read_text(encoding="utf-8").splitlines() if clips.is_file() else []
        for line in filter(str.strip, lines):
            item_id = json.loads(line).get("test_item_id")
            if item_id not in ids:
                problems.append(f"{name} clip points at {item_id!r}, which {source or '?'} lacks")
    return problems


def all_leaks(root: Path = SETS_DIR, prompts_dir: Path = PROMPTS_DIR) -> list[str]:
    return (
        duplicate_transcripts(root)
        + duplicate_ids(root)
        + prompt_leaks(root, prompts_dir)
        + claude_drafts_in_test(root)
        + orphan_clips(root)
    )
