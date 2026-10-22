"""Runtime configuration, read from the environment and from backend/.env when present.

Defaults follow docs/plans/part-1-extraction-call.md. The API key is a secret: it never appears in
reprs, dumps or logs, and when it is unset the SDK resolves credentials itself.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from commitment_tracker.extractor.anthropic_adapter import Effort


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    extractor_model: str = Field(default="claude-opus-5-5", min_length=1)
    extractor_effort: Effort = "medium"
    extractor_max_tokens: int = Field(default=16_000, gt=0)
    prompt_version: str = "v1"
    model_timeout_seconds: float = Field(default=60.0, gt=0)
    anthropic_api_key: SecretStr | None = None
    # Audio storage: unset locally, where POST /uploads answers 503.
    audio_bucket: str | None = Field(default=None, min_length=1)
    upload_url_ttl_seconds: int = Field(default=300, gt=0)
    jobs_table: str | None = Field(default=None, min_length=1)
    guardrails_table: str | None = Field(default=None, min_length=1)
    daily_budget_usd: float = Field(default=5.0, gt=0)
