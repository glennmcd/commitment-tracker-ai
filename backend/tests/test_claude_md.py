"""CLAUDE.md stays small: every session loads it and pays for it on every model call.

Lower CAP_BYTES as the file shrinks; never raise it. Move detail that only some
tasks need into docs/ and point to it from CLAUDE.md.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the repo root: this file is backend/tests/...
CAP_BYTES = 4_096


def over_cap(root: Path, cap: int) -> str | None:
    """Why the root CLAUDE.md is too large, or None when it fits (or does not exist)."""
    path = root / "CLAUDE.md"
    size = path.stat().st_size if path.is_file() else 0
    if size <= cap:
        return None
    return (
        f"CLAUDE.md is {size} bytes, over the {cap}-byte cap. Move detail that only some tasks "
        "need into docs/ and point to it."
    )


def test_claude_md_stays_under_the_cap() -> None:
    message = over_cap(ROOT, CAP_BYTES)
    assert message is None, message
