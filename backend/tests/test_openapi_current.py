"""The committed openapi.json matches the app; the Part 2 frontend generates its client from it."""

import json

from commitment_tracker.api.export_openapi import OPENAPI_PATH, render_openapi


def test_committed_openapi_is_current() -> None:
    assert OPENAPI_PATH.is_file(), "run `uv run export-openapi` from backend/"
    committed = OPENAPI_PATH.read_text(encoding="utf-8")
    assert committed == render_openapi(), "openapi.json is stale: run `uv run export-openapi`"


def test_rendered_spec_is_stable_json() -> None:
    first = render_openapi()
    assert first == render_openapi()
    assert first.endswith("\n")
    assert json.loads(first)["info"]["title"] == "Commitment Tracker AI"
