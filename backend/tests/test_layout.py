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
    "schemas": {"settings", "extractor", "api", "evaluation"},
    "extractor": {"api", "evaluation"},
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
