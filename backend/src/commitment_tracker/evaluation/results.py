"""The outcome of running the extractor on one evaluation item."""

from dataclasses import dataclass

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.schemas import AnalyzeResponse


@dataclass(frozen=True)
class ItemResult:
    item: EvalItem
    response: AnalyzeResponse | None  # None when extraction failed
    error: str | None  # the failure code, e.g. "model_output_invalid"
    cached: bool
