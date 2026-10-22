"""Builds the production extractor (Anthropic adapter plus a prompt version) from settings."""

from commitment_tracker.extractor.anthropic_adapter import AnthropicAdapter
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.settings import Settings


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
