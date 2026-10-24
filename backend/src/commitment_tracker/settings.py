"""Runtime configuration, read from the environment and from backend/.env when present.

Defaults follow docs/plans/part-1-extraction-call.md. The API key is a secret: it never appears in
reprs, dumps or logs, and when it is unset the SDK resolves credentials itself.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from commitment_tracker.extractor.anthropic_adapter import Effort
from commitment_tracker.extractor.two_stage import NON_NONE
from commitment_tracker.schemas import Label

# Named configurations for evaluation runs: one model, or (screen, extract) for the two-stage
# pipeline (ADR 0011). Reports and the regression gate refer to runs by these names.
CONFIGURATIONS: dict[str, tuple[str, ...]] = {
    "haiku": ("claude-haiku-5-5",),
    "sonnet": ("claude-sonnet-5-5",),
    "opus": ("claude-opus-5-5",),
    "two-stage": ("claude-haiku-5-5", "claude-opus-5-5"),
}


def configuration_for_model(model: str) -> str:
    """The configuration a bare model id belongs to, or the id itself when none matches."""
    return next((name for name, models in CONFIGURATIONS.items() if models == (model,)), model)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    extractor_model: str = Field(default="claude-opus-5-5", min_length=1)
    extractor_effort: Effort = "medium"
    extractor_max_tokens: int = Field(default=16_000, gt=0)
    prompt_version: str = "v1"
    # Screen labels that send a turn to the extract model in the two-stage pipeline.
    two_stage_flag_labels: frozenset[Label] = NON_NONE
    model_timeout_seconds: float = Field(default=60.0, gt=0)
    anthropic_api_key: SecretStr | None = None
    # On Lambda the key lives in SSM; this names its SecureString parameter (lambda_handlers).
    anthropic_api_key_parameter: str | None = Field(default=None, min_length=1)
    # Audio storage: unset locally, where POST /uploads answers 503.
    audio_bucket: str | None = Field(default=None, min_length=1)
    upload_url_ttl_seconds: int = Field(default=300, gt=0)
    jobs_table: str | None = Field(default=None, min_length=1)
    guardrails_table: str | None = Field(default=None, min_length=1)
    feedback_table: str | None = Field(default=None, min_length=1)
    daily_budget_usd: float = Field(default=5.0, gt=0)
    worker_function_name: str | None = Field(default=None, min_length=1)
    # The private bucket of evaluation clips (stack output EvalAudioBucketName); `eval-audio` only.
    eval_audio_bucket: str | None = Field(default=None, min_length=1)
