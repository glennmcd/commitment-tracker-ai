"""Released prompt versions are unchangeable: prompts/manifest.json lists the sha256 of each one.

Editing a released prompt in place would leave reports and the baseline naming a version whose text
has changed. Change the prompt by adding a new version file and a manifest entry for it.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
PROMPTS_DIR = ROOT / "src" / "commitment_tracker" / "extractor" / "prompts"
MANIFEST = PROMPTS_DIR / "manifest.json"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_problems(prompts_dir: Path, manifest: Path) -> list[str]:
    """Why the prompt files and the manifest disagree, or [] when they agree."""
    listed: dict[str, str] = json.loads(manifest.read_text(encoding="utf-8"))
    problems = []
    for name, digest in sorted(listed.items()):
        path = prompts_dir / name
        if not path.is_file():
            problems.append(f"{name} is listed in manifest.json but the file is missing")
        elif sha256_of(path) != digest:
            problems.append(
                f"{name} changed since its release. Released prompts are unchangeable: put the new "
                f"text in a new version (prompts/v<N+1>.md), then add its entry to manifest.json"
            )
    for path in sorted(prompts_dir.glob("*.md")):
        if path.name not in listed:
            problems.append(
                f"{path.name} has no entry in manifest.json. Add "
                f'"{path.name}": "{sha256_of(path)}" to it (sha256sum gives the same value)'
            )
    return problems


def test_released_prompts_match_their_manifest_hashes() -> None:
    assert manifest_problems(PROMPTS_DIR, MANIFEST) == []


def test_a_one_character_edit_to_a_listed_prompt_is_reported(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    released = (PROMPTS_DIR / "v1.md").read_bytes()
    (prompts / "v1.md").write_bytes(released + b" ")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"v1.md": hashlib.sha256(released).hexdigest()}))

    problems = manifest_problems(prompts, manifest)

    assert len(problems) == 1
    assert "v1.md changed since its release" in problems[0]
    assert "new version" in problems[0]


def test_a_new_prompt_without_a_manifest_entry_is_reported(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "v2.md").write_text("A new prompt.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    problems = manifest_problems(prompts, manifest)

    assert len(problems) == 1
    assert "v2.md has no entry in manifest.json" in problems[0]
    assert hashlib.sha256(b"A new prompt.\n").hexdigest() in problems[0]


def test_a_listed_prompt_that_is_gone_is_reported(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"v1.md": "0" * 64}))

    assert manifest_problems(prompts, manifest) == [
        "v1.md is listed in manifest.json but the file is missing"
    ]
