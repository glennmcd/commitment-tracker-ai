"""The `--help` text of every evaluation entry point and subcommand, pinned to a snapshot.

The snapshot is `help_snapshot.txt` beside this file. Regenerate it with `render()` from this
module, run with COLUMNS=80, and only for an intended change to a command's help.
"""

import contextlib
import io
from collections.abc import Callable
from pathlib import Path

import pytest

from commitment_tracker.evaluation import audio_cli, cli, gate_cli

SNAPSHOT = Path(__file__).parent / "help_snapshot.txt"

# argparse wraps help to the terminal width; the snapshot is taken at this width.
WIDTH = "80"

HELP_CALLS: list[tuple[str, Callable[[], int]]] = [
    ("eval", lambda: cli.main(["--help"])),
    ("eval import", lambda: cli.main(["import", "--help"])),
    ("eval review", lambda: cli.main(["review", "--help"])),
    ("eval promote", lambda: cli.main(["promote", "--help"])),
    ("eval rescore", lambda: cli.main(["rescore", "--help"])),
    ("eval-sets", lambda: cli.sets_main(["--help"])),
    ("eval-compare", lambda: cli.compare_main(["--help"])),
    ("eval-gate", lambda: gate_cli.gate_main(["--help"])),
    ("eval-audio", lambda: audio_cli.audio_main(["--help"])),
    ("eval-audio make", lambda: audio_cli.audio_main(["make", "--help"])),
    ("eval-audio add", lambda: audio_cli.audio_main(["add", "--help"])),
    ("eval-audio upload", lambda: audio_cli.audio_main(["upload", "--help"])),
    ("eval-audio fetch", lambda: audio_cli.audio_main(["fetch", "--help"])),
    ("eval-export-site", lambda: cli.export_site_main(["--help"])),
]


def render() -> str:
    """Every entry point's help, each under a `$ name --help` heading."""
    sections = []
    for name, call in HELP_CALLS:
        buffer = io.StringIO()
        # argparse prints help to stdout and exits 0.
        with contextlib.redirect_stdout(buffer), pytest.raises(SystemExit) as exit_info:
            call()
        assert exit_info.value.code == 0, name
        sections.append(f"$ {name} --help\n{buffer.getvalue()}")
    return "\n".join(sections)


def test_help_text_matches_the_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", WIDTH)
    assert render() == SNAPSHOT.read_text(encoding="utf-8")


def test_every_entry_point_is_in_the_snapshot() -> None:
    lines = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    headings = [line for line in lines if line.startswith("$ ")]
    assert headings == [f"$ {name} --help" for name, _ in HELP_CALLS]
