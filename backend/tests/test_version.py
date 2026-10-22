"""The package version lives in one place: commitment_tracker.__version__."""

import re
import tomllib
from pathlib import Path

import commitment_tracker

BACKEND = Path(__file__).resolve().parent.parent


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", commitment_tracker.__version__)


def test_pyproject_reads_the_version_from_init() -> None:
    # A static version in pyproject.toml would also be recorded in uv.lock, which release-please
    # can't update, so every release PR would leave the lockfile stale.
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in project["project"]
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/commitment_tracker/__init__.py"


def test_lockfile_does_not_pin_the_project_version() -> None:
    lock = (BACKEND / "uv.lock").read_text(encoding="utf-8")
    entry = lock.split('name = "commitment-tracker"\n', 1)[1].split("\n\n", 1)[0]
    assert not entry.startswith("version")
