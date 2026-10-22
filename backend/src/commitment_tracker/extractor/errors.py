"""Typed failures of the extraction pipeline. Messages never contain transcript text.

Each class has a stable `code` that the API and the evaluation reports use to name the failure.
"""

from typing import ClassVar


class ExtractionError(Exception):
    """Base class: the transcript could not be analysed."""

    code: ClassVar[str] = "extraction_failed"


class ModelUnavailable(ExtractionError):
    """The model API failed after the SDK's own retries (rate limit, server error, timeout)."""

    code = "model_unavailable"


class ModelRefused(ExtractionError):
    """The model declined the request (stop_reason "refusal"), after any server-side fallback."""

    code = "model_refused"

    def __init__(self, category: str | None) -> None:
        super().__init__(f"model refused the request (category: {category or 'unknown'})")
        self.category = category


class ModelOutputInvalid(ExtractionError):
    """The model's output failed validation twice: the first reply and the one retry."""

    code = "model_output_invalid"

    def __init__(self, errors: str) -> None:
        super().__init__(f"model output failed validation after one retry: {errors}")
        self.errors = errors
