"""Builds the production extractor (Anthropic adapter plus a prompt version) from settings, and the
analyzer for a named configuration (one model, or the two-stage pipeline)."""

from collections.abc import Callable

from commitment_tracker.extractor.analyzer import Analyzer
from commitment_tracker.extractor.anthropic_adapter import AnthropicAdapter
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.extractor.two_stage import TwoStageExtractor
from commitment_tracker.settings import CONFIGURATIONS, Settings


class UnknownConfiguration(ValueError):
    pass


def build_extractor(settings: Settings, *, model: str | None = None) -> Extractor:
    """`model` overrides the configured model, for evaluation runs that compare models."""
    key = settings.anthropic_api_key
    adapter = AnthropicAdapter(
        model or settings.extractor_model,
        effort=settings.extractor_effort,
        max_tokens=settings.extractor_max_tokens,
        timeout_seconds=settings.model_timeout_seconds,
        api_key=key.get_secret_value() if key is not None else None,
    )
    return Extractor(adapter, load_prompt(settings.prompt_version))


def build_analyzer(
    settings: Settings,
    configuration: str,
    *,
    build: Callable[[str], Extractor] | None = None,
    wrap: Callable[[Extractor], Analyzer] | None = None,
) -> Analyzer:
    """The analyzer for a configuration in `CONFIGURATIONS`. `build` makes the extractor for a
    model id (default: the Anthropic one) and `wrap` decorates each stage, which is how evaluation
    puts a response cache around every stage rather than around the whole pipeline."""
    models = CONFIGURATIONS.get(configuration)
    if models is None:
        known = ", ".join(CONFIGURATIONS)
        raise UnknownConfiguration(f"configuration must be one of {known}, not {configuration!r}")
    make = build or (lambda model: build_extractor(settings, model=model))

    def stage(model: str) -> Analyzer:
        extractor = make(model)
        extractor.name = configuration if len(models) == 1 else model
        return wrap(extractor) if wrap else extractor

    if len(models) == 1:
        return stage(models[0])
    screen, extract = models
    return TwoStageExtractor(
        stage(screen), stage(extract), flag_labels=settings.two_stage_flag_labels
    )
