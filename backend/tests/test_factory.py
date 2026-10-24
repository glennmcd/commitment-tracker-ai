"""Named configurations: one table maps names to models; the factory builds each analyzer."""

import pytest

from commitment_tracker.extractor.analyzer import Analyzer
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.factory import UnknownConfiguration, build_analyzer
from commitment_tracker.extractor.pricing import PRICES
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.extractor.two_stage import TwoStageExtractor
from commitment_tracker.schemas import LEDGER_LABELS
from commitment_tracker.settings import CONFIGURATIONS, Settings, configuration_for_model
from tests.fakes import FakeAdapter


def fake_build(model: str) -> Extractor:
    return Extractor(FakeAdapter(model=model), load_prompt("v1"))


def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.mark.parametrize(
    ("name", "model"),
    [("haiku", "claude-haiku-5-5"), ("sonnet", "claude-sonnet-5-5"), ("opus", "claude-opus-5-5")],
)
def test_single_model_configurations(name: str, model: str) -> None:
    analyzer = build_analyzer(settings(), name, build=fake_build)
    assert isinstance(analyzer, Extractor)
    configuration = analyzer.describe()
    assert (configuration.name, configuration.stages) == (name, {"extract": model})


def test_two_stage_is_a_haiku_screen_and_an_opus_extract() -> None:
    analyzer = build_analyzer(settings(), "two-stage", build=fake_build)
    assert isinstance(analyzer, TwoStageExtractor)
    assert analyzer.describe().stages == {
        "screen": "claude-haiku-5-5",
        "extract": "claude-opus-5-5",
    }


def test_the_flag_rule_comes_from_settings() -> None:
    strict = Settings(_env_file=None, two_stage_flag_labels=frozenset(LEDGER_LABELS))
    analyzer = build_analyzer(strict, "two-stage", build=fake_build)
    assert isinstance(analyzer, TwoStageExtractor)
    assert analyzer.flag_labels == LEDGER_LABELS


def test_wrap_decorates_every_stage() -> None:
    wrapped: list[str] = []

    def wrap(extractor: Extractor) -> Analyzer:
        wrapped.append(extractor.adapter.model)
        return extractor

    build_analyzer(settings(), "two-stage", build=fake_build, wrap=wrap)
    assert wrapped == ["claude-haiku-5-5", "claude-opus-5-5"]


def test_unknown_configuration() -> None:
    with pytest.raises(UnknownConfiguration, match="haiku, sonnet, opus, two-stage"):
        build_analyzer(settings(), "gpt", build=fake_build)


def test_configuration_for_a_bare_model_id() -> None:
    assert configuration_for_model("claude-opus-5-5") == "opus"
    assert configuration_for_model("claude-opus-4-1") == "claude-opus-4-1"


def test_every_configured_model_has_a_price() -> None:
    assert {m for models in CONFIGURATIONS.values() for m in models} <= set(PRICES)
