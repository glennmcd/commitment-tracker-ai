"""Fixtures shared by the evaluation tests."""

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.settings import Settings
from tests.eval.test_runner import all_none
from tests.eval.test_set_loading import write_set
from tests.fakes import FunctionAdapter

TODAY = date(2026, 10, 25)
logger = logging.getLogger(__name__)


def draft(item_id: str, text: str = "I'll send it Friday.", **overrides: Any) -> dict[str, Any]:
    """A line as a generator writes it: no provenance, no review."""
    data: dict[str, Any] = {
        "id": item_id,
        "call_date": "2026-10-21",
        "turns": [{"speaker": "seller", "text": text}],
        "tags": [],
        "expected": [
            {
                "turn_index": 0,
                "label": "COMMITMENT",
                "quote": text,
                "owner": "seller",
                "recipient": "buyer",
                "action_keywords": ["send"],
                "due_raw": "Friday",
                "due_resolved": "2026-10-23",
                "precision": "day",
                "condition": None,
            }
        ],
        "note": None,
    }
    data.update(overrides)
    return data


# this fixture sets up a root directory with a dev set containing one item
# and is passed into the test functions
@pytest.fixture
def root(tmp_path: Path) -> Path:
    logger.debug("Setting up root directory at %s", tmp_path)
    sets = tmp_path / "sets"
    write_set(
        sets,
        "dev",
        [
            {
                **draft("d-01", "Our SLA is four hours for every priority one ticket."),
                "expected": [
                    {
                        "turn_index": 0,
                        "label": "NONE",
                        "quote": "Our SLA is four hours for every priority one ticket.",
                    }
                ],
                "provenance": "spec",
                "review": "accepted",
            }
        ],
        role="dev",
        gated=False,
    )
    return sets


def write_source(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "gemini.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def standard_options(root: Path, **overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "batch": "gem01",
        "provenance": "gemini-3-pro",
        "generation_prompt": "prompt-v1",
        "root": root,
        "today": TODAY,
    }
    options.update(overrides)
    return options


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Replaces the Anthropic extractor; records (model, prompt version) for each build."""
    built: list[tuple[str, str]] = []

    def build(settings: Settings, *, model: str | None = None) -> Extractor:
        chosen = model or settings.extractor_model
        built.append((chosen, settings.prompt_version))
        return Extractor(
            FunctionAdapter(all_none, model=chosen), load_prompt(settings.prompt_version)
        )

    monkeypatch.setattr(cli, "build_extractor", build)
    return built
