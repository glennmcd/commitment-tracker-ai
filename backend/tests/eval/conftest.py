"""Fixtures shared by the evaluation tests."""

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.settings import Settings
from tests.eval.test_runner import all_none
from tests.fakes import FunctionAdapter


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
