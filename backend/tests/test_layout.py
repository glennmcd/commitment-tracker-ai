"""Import rules between the packages under src/commitment_tracker (CLAUDE.md, "Import layering").

`schemas` is the shared contract and imports nothing of ours; the extractor never reaches into the
API or the evaluation; the evaluation drives the extractor directly, never through the API.
"""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "commitment_tracker"
FIRST_PARTY = "commitment_tracker"

# module or package under commitment_tracker -> first-party modules it must not import
RULES: dict[str, set[str]] = {
    "schemas": {"settings", "extractor", "transcription", "api", "evaluation"},
    "extractor": {"api", "evaluation"},
    "transcription": {"extractor", "jobs", "api", "evaluation"},
    "jobs": {"api", "evaluation"},
    "feedback": {"api", "evaluation"},
    "guardrails": {
        "schemas",
        "settings",
        "extractor",
        "transcription",
        "jobs",
        "api",
        "evaluation",
    },
    "evaluation": {"api"},
}


def imported_modules(root: Path, name: str) -> set[str]:
    """First-party top-level modules imported anywhere in `root/name` (a package or `name.py`)."""
    package = root / name
    files = list(package.rglob("*.py")) if package.is_dir() else [root / f"{name}.py"]
    found: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    base = node.module or ""
                else:
                    # Relative imports stay inside the package unless they climb to the top level.
                    if node.level <= len(path.relative_to(root).parts) - 1:
                        continue
                    base = ".".join(filter(None, [FIRST_PARTY, node.module]))
                # `from commitment_tracker import api` names the module in the alias.
                if base == FIRST_PARTY:
                    modules = [f"{FIRST_PARTY}.{alias.name}" for alias in node.names]
                else:
                    modules = [base]
            else:
                continue
            for module in modules:
                parts = module.split(".")
                if parts[0] == FIRST_PARTY and len(parts) > 1:
                    found.add(parts[1])
    return found


@pytest.mark.parametrize("name", sorted(RULES))
def test_layout_modules_exist(name: str) -> None:
    assert (PACKAGE_ROOT / name).is_dir() or (PACKAGE_ROOT / f"{name}.py").is_file()


@pytest.mark.parametrize(("name", "forbidden"), sorted(RULES.items()))
def test_import_rules(name: str, forbidden: set[str]) -> None:
    assert imported_modules(PACKAGE_ROOT, name).isdisjoint(forbidden)


# The checker itself, on a throwaway tree, so a broken parser can't make the rules pass vacuously.


def write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    "source",
    [
        "import commitment_tracker.api\n",
        "from commitment_tracker.api.app import create_app\n",
        "from commitment_tracker import api\n",
        "from ..api import app\n",
        "from .. import api\n",
    ],
)
def test_checker_finds_forbidden_import(tmp_path: Path, source: str) -> None:
    write(tmp_path, "extractor/__init__.py", "")
    write(tmp_path, "extractor/pipeline.py", source)
    assert "api" in imported_modules(tmp_path, "extractor")


def test_checker_handles_single_module(tmp_path: Path) -> None:
    write(tmp_path, "schemas.py", "from commitment_tracker.settings import Settings\n")
    assert imported_modules(tmp_path, "schemas") == {"settings"}


def test_checker_ignores_imports_inside_the_package(tmp_path: Path) -> None:
    write(tmp_path, "extractor/__init__.py", "from .dates import resolve\n")
    write(tmp_path, "extractor/dates.py", "import datetime\nfrom dateutil import relativedelta\n")
    assert imported_modules(tmp_path, "extractor") == set()


# The Anthropic SDK: only the adapter may import it, so tests can swap in the fake adapter.

SDK = "anthropic"
SDK_ADAPTER = "extractor/anthropic_adapter.py"


def top_level_imports(source: str) -> set[str]:
    """Top-level names of the absolute imports in `source`, whatever their alias or depth."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def modules_importing(root: Path, top_level: str) -> list[str]:
    """Paths under `root`, relative to it, of the modules that import `top_level`."""
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if top_level in top_level_imports(path.read_text(encoding="utf-8"))
    )


def test_only_the_adapter_imports_the_anthropic_sdk() -> None:
    assert modules_importing(PACKAGE_ROOT, SDK) == [SDK_ADAPTER]


@pytest.mark.parametrize(
    "source",
    [
        "import anthropic\n",
        "import anthropic as a\n",
        "from anthropic import Anthropic\n",
        "from anthropic import Anthropic as Client\n",
        "from anthropic.types.beta import BetaMessage\n",
        "import anthropic.types.beta\n",
        "from anthropic import *\n",
        "def build():\n    import anthropic\n",
        "try:\n    import anthropic\nexcept ImportError:\n    pass\n",
    ],
)
def test_sdk_checker_finds_import(source: str) -> None:
    assert SDK in top_level_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "import anthropic_helpers\n",
        "from anthropics import thing\n",
        "from commitment_tracker.extractor import anthropic_adapter\n",
        "from . import anthropic\n",
        "import json  # mentions anthropic only in a comment\n",
    ],
)
def test_sdk_checker_ignores_lookalikes(source: str) -> None:
    assert SDK not in top_level_imports(source)


@pytest.mark.parametrize(
    "source",
    ["import anthropic as a\n", "from anthropic import Anthropic\n"],
)
def test_sdk_rule_catches_a_stray_import_in_the_tree(tmp_path: Path, source: str) -> None:
    write(tmp_path, "extractor/__init__.py", "")
    write(tmp_path, SDK_ADAPTER, "import anthropic\n")
    write(tmp_path, "extractor/extractor.py", source)
    assert modules_importing(tmp_path, SDK) == [SDK_ADAPTER, "extractor/extractor.py"]
