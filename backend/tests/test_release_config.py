"""release-please (docs/releasing.md) works from files that must agree, and its workflow holds a
token that can write to the repository. These tests catch a hand-edited version or a loosened
workflow before a release goes wrong. The workflow is checked as text, so no YAML parser is needed.
"""

import json
import re
from pathlib import Path
from typing import Any

import commitment_tracker

ROOT = Path(__file__).resolve().parents[2]
CONFIG = "release-please-config.json"
MANIFEST = ".release-please-manifest.json"
WORKFLOW = ".github/workflows/release-please.yml"
VERSION_FILE = "backend/src/commitment_tracker/__init__.py"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def config() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(read(CONFIG))
    return data


# --- Configuration -------------------------------------------------------------------------------


def test_one_version_for_the_repository_with_plain_tags() -> None:
    packages = config()["packages"]
    assert list(packages) == ["."]
    package = packages["."]
    assert package["release-type"] == "python"
    # With a component in the tag, releases would be named commitment-tracker-v1.2.3.
    assert package["include-component-in-tag"] is False
    assert package["bump-minor-pre-major"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", config()["bootstrap-sha"])


def test_manifest_matches_the_package_version() -> None:
    manifest = json.loads(read(MANIFEST))
    assert manifest == {".": commitment_tracker.__version__}


def test_the_version_file_is_an_annotated_extra_file() -> None:
    # The python release type only looks for pyproject.toml and __init__.py at the package path,
    # which is the repository root here, so the backend's __init__.py is listed explicitly.
    assert config()["packages"]["."]["extra-files"] == [{"type": "generic", "path": VERSION_FILE}]
    annotated = [
        line for line in read(VERSION_FILE).splitlines() if "x-release-please-version" in line
    ]
    assert annotated == [
        f'__version__ = "{commitment_tracker.__version__}"  # x-release-please-version'
    ]


# --- Workflow ------------------------------------------------------------------------------------


def test_runs_only_on_pushes_to_main() -> None:
    workflow = read(WORKFLOW)
    on_block = workflow.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert on_block == "  push:\n    branches: [main]"


def test_asks_for_exactly_the_three_permissions_the_action_documents() -> None:
    block = read(WORKFLOW).split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
    lines = sorted(line.strip() for line in block.splitlines() if not line.strip().startswith("#"))
    assert lines == ["contents: write", "issues: write", "pull-requests: write"]


def test_runs_the_action_pinned_to_a_commit() -> None:
    # A tag can be moved, and this job can write to the repository.
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", read(WORKFLOW), re.MULTILINE)
    assert len(uses) == 1
    assert re.fullmatch(r"googleapis/release-please-action@[0-9a-f]{40}", uses[0])


def test_runs_no_shell_commands() -> None:
    # No step script means no repository content or secret reaches a shell.
    assert not re.search(r"^\s*-?\s*run:", read(WORKFLOW), re.MULTILINE)


def test_points_the_action_at_the_config_and_manifest() -> None:
    workflow = read(WORKFLOW)
    assert f"config-file: {CONFIG}" in workflow
    assert f"manifest-file: {MANIFEST}" in workflow


def test_falls_back_to_the_built_in_token() -> None:
    assert "token: ${{ secrets.RELEASE_PLEASE_TOKEN || github.token }}" in read(WORKFLOW)
