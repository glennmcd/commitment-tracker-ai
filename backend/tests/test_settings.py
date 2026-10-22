"""Configuration from the environment (and backend/.env when present)."""

from typing import Any

import pytest
from pydantic import ValidationError

from commitment_tracker.settings import Settings


def settings(**overrides: Any) -> Settings:
    # _env_file=None keeps a developer's backend/.env out of the tests.
    return Settings(_env_file=None, **overrides)


def test_defaults_match_the_design_note(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("EXTRACTOR_MODEL", "EXTRACTOR_EFFORT", "PROMPT_VERSION", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    s = settings()
    assert s.extractor_model == "claude-opus-5-5"
    assert s.extractor_effort == "medium"
    assert s.extractor_max_tokens == 16_000
    assert s.prompt_version == "v1"
    assert s.model_timeout_seconds == 60.0
    assert s.anthropic_api_key is None


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACTOR_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("EXTRACTOR_EFFORT", "low")
    monkeypatch.setenv("PROMPT_VERSION", "v2")
    s = settings()
    assert (s.extractor_model, s.extractor_effort, s.prompt_version) == (
        "claude-haiku-5-5",
        "low",
        "v2",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("extractor_effort", "extreme"),
        ("extractor_max_tokens", 0),
        ("model_timeout_seconds", -1),
        ("extractor_model", ""),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        settings(**{field: value})


def test_api_key_never_appears_in_repr_or_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    s = settings()
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-test-not-real"
    assert "sk-ant-test-not-real" not in repr(s)
    assert "sk-ant-test-not-real" not in str(s.model_dump())


def test_upload_storage_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUDIO_BUCKET", raising=False)
    assert settings().audio_bucket is None
    assert settings().upload_url_ttl_seconds == 300
    monkeypatch.setenv("AUDIO_BUCKET", "audio-bucket")
    assert settings().audio_bucket == "audio-bucket"


def test_table_names_default_to_unset_and_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("JOBS_TABLE", "GUARDRAILS_TABLE"):
        monkeypatch.delenv(name, raising=False)
    assert (settings().jobs_table, settings().guardrails_table) == (None, None)
    monkeypatch.setenv("JOBS_TABLE", "jobs")
    monkeypatch.setenv("GUARDRAILS_TABLE", "guardrails")
    assert (settings().jobs_table, settings().guardrails_table) == ("jobs", "guardrails")


def test_lambda_settings_default_to_unset_and_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("ANTHROPIC_API_KEY_PARAMETER", "WORKER_FUNCTION_NAME"):
        monkeypatch.delenv(name, raising=False)
    assert settings().anthropic_api_key_parameter is None
    assert settings().worker_function_name is None
    monkeypatch.setenv("ANTHROPIC_API_KEY_PARAMETER", "/p")
    monkeypatch.setenv("WORKER_FUNCTION_NAME", "worker")
    assert (settings().anthropic_api_key_parameter, settings().worker_function_name) == (
        "/p",
        "worker",
    )


def test_upload_ttl_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        settings(upload_url_ttl_seconds=0)


def test_daily_budget_defaults_to_five_dollars_and_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DAILY_BUDGET_USD", raising=False)
    assert settings().daily_budget_usd == 5.0
    monkeypatch.setenv("DAILY_BUDGET_USD", "2.5")
    assert settings().daily_budget_usd == 2.5
    with pytest.raises(ValidationError):
        settings(daily_budget_usd=0)
