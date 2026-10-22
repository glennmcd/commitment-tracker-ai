"""Writes the app's OpenAPI schema to openapi.json at the repository root.

`uv run export-openapi` rewrites it; `uv run export-openapi --check` exits 1 when it is stale.
The Part 2 frontend generates its typed client from this file.
"""

import argparse
import json
import sys
from pathlib import Path

from commitment_tracker.api.app import create_app

# backend/src/commitment_tracker/api/export_openapi.py -> the repository root
OPENAPI_PATH = Path(__file__).resolve().parents[4] / "openapi.json"


def render_openapi() -> str:
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if openapi.json is stale")
    args = parser.parse_args(argv)

    rendered = render_openapi()
    current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.is_file() else None
    if args.check:
        if current != rendered:
            print(f"{OPENAPI_PATH} is stale; run `uv run export-openapi`", file=sys.stderr)
            return 1
        return 0
    OPENAPI_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
