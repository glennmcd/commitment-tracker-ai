"""Released prompt versions are immutable: `prompts/manifest.json` pins each prompt file's sha256.

Evaluation reports and the baseline name a prompt by its version, so editing a released file in
place would leave them describing text that no longer exists. Changing a prompt means adding a
new version.
"""

import hashlib
import json
from pathlib import Path

PROMPTS = (
    Path(__file__).resolve().parent.parent / "src" / "commitment_tracker" / "extractor" / "prompts"
)
ADD_VERSION = (
    "add a new version instead of editing a released one: write prompts/<next>.md, then add its "
    "sha256 to prompts/manifest.json (`sha256sum prompts/<next>.md`)"
)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_problems(prompts: Path) -> list[str]:
    listed: dict[str, str] = json.loads((prompts / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    for name, digest in sorted(listed.items()):
        path = prompts / name
        if not path.is_file():
            problems.append(f"{name} is in manifest.json but the file is missing; restore it")
        elif (actual := sha256_of(path)) != digest:
            problems.append(
                f"{name} changed since it was released (manifest has {digest[:12]}, file has "
                f"{actual[:12]}); {ADD_VERSION}"
            )
    for path in sorted(prompts.glob("v*.md")):
        if path.name not in listed:
            problems.append(f"{path.name} has no entry in manifest.json; {ADD_VERSION}")
    return problems


def test_released_prompts_match_the_manifest() -> None:
    problems = manifest_problems(PROMPTS)
    assert not problems, "\n".join(problems)


def test_editing_a_released_prompt_by_one_character_fails(tmp_path: Path) -> None:
    original = (PROMPTS / "v1.md").read_bytes()
    edited = original.replace(b"e", b"f", 1)
    assert edited != original
    (tmp_path / "v1.md").write_bytes(edited)
    (tmp_path / "manifest.json").write_bytes((PROMPTS / "manifest.json").read_bytes())

    problems = manifest_problems(tmp_path)

    assert len(problems) == 1
    assert "v1.md changed since it was released" in problems[0]
    assert "add a new version" in problems[0]


def test_a_new_prompt_without_a_manifest_entry_fails(tmp_path: Path) -> None:
    for name in ("v1.md", "manifest.json"):
        (tmp_path / name).write_bytes((PROMPTS / name).read_bytes())
    (tmp_path / "v2.md").write_text("draft prompt", encoding="utf-8")

    problems = manifest_problems(tmp_path)

    assert len(problems) == 1
    assert "v2.md has no entry in manifest.json" in problems[0]
    assert "sha256sum prompts/<next>.md" in problems[0]


def test_a_listed_prompt_that_is_deleted_fails(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_bytes((PROMPTS / "manifest.json").read_bytes())

    problems = manifest_problems(tmp_path)

    assert problems == ["v1.md is in manifest.json but the file is missing; restore it"]
