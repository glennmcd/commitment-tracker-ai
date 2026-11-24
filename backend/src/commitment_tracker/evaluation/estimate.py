"""What a run will cost before it runs: `uv run eval --estimate`. It makes no model calls.

Each stage asks the response cache which of its requests are already answered; the rest are misses.
A miss is priced at the mean token use of cached responses for the same model and prompt, with
`pricing.py`'s rates for that model. A model with no cached responses yet is priced from the other
models' responses for the same prompt, which is a rough guide (the tokenizers differ a little).

Two-stage: the screen's requests are known exactly. An extract window exists only once its item's
screen response is known, so an item with an uncached screen is counted but its windows are not
priced; the estimate is then a lower bound.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from commitment_tracker.evaluation.cache import CachedAnalyzer, ResponseCache
from commitment_tracker.extractor.adapter import Usage
from commitment_tracker.extractor.analyzer import Analyzer
from commitment_tracker.extractor.pricing import cost_usd
from commitment_tracker.extractor.two_stage import (
    TwoStageExtractor,
    flagged_turns,
    window_request,
    windows,
)
from commitment_tracker.schemas import AnalyzeRequest, Metadata


@dataclass(frozen=True)
class StageEstimate:
    stage: str  # "extract" for a single model, "screen" or "extract" for two-stage
    model: str
    calls: int
    misses: int
    cost_usd: float | None  # None: the model has no known price, or nothing to price it from
    note: str | None = None


@dataclass(frozen=True)
class RunEstimate:
    stages: list[StageEstimate]
    unpriced_items: int  # two-stage items whose screen is uncached, so their windows are unknown

    @property
    def calls(self) -> int:
        return sum(stage.calls for stage in self.stages)

    @property
    def misses(self) -> int:
        return sum(stage.misses for stage in self.stages)

    @property
    def cost_usd(self) -> float | None:
        costs = [stage.cost_usd for stage in self.stages if stage.misses]
        return None if None in costs else sum(c for c in costs if c is not None)


def _stage_of(analyzer: Analyzer) -> CachedAnalyzer:
    assert isinstance(analyzer, CachedAnalyzer), "every stage is built behind the response cache"
    return analyzer


def _mean_usage(
    stored: list[Metadata], model: str, prompt_version: str
) -> tuple[Usage, bool] | None:
    """Mean token use of the cached responses, and whether they came from other models."""
    same_prompt = [m for m in stored if m.prompt_version == prompt_version]
    own = [m for m in same_prompt if m.model == model]
    basis = own or same_prompt
    if not basis:
        return None
    count = len(basis)
    usage = Usage(
        input_tokens=round(sum(m.input_tokens for m in basis) / count),
        output_tokens=round(sum(m.output_tokens for m in basis) / count),
        cache_creation_input_tokens=round(
            sum(m.cache_creation_input_tokens for m in basis) / count
        ),
        cache_read_input_tokens=round(sum(m.cache_read_input_tokens for m in basis) / count),
    )
    return usage, not own


def _price(
    stage: str, analyzer: CachedAnalyzer, calls: int, misses: int, stored: list[Metadata]
) -> StageEstimate:
    model = analyzer.describe().stages["extract"]
    prompt_version = analyzer.describe().prompt_version
    if misses == 0:
        return StageEstimate(stage, model, calls, misses, cost_usd=0.0)
    mean = _mean_usage(stored, model, prompt_version)
    if mean is None:
        reason = f"no cached responses for prompt {prompt_version} to price from"
        return StageEstimate(stage, model, calls, misses, cost_usd=None, note=reason)
    usage, from_other_models = mean
    per_call = cost_usd(model, usage)
    if per_call is None:
        return StageEstimate(
            stage, model, calls, misses, cost_usd=None, note=f"no price for {model}"
        )
    note = (
        f"no cached {model} responses; priced from other models' responses for {prompt_version}"
        if from_other_models
        else None
    )
    return StageEstimate(stage, model, calls, misses, cost_usd=misses * per_call, note=note)


def estimate_run(
    requests: Iterable[AnalyzeRequest], analyzer: Analyzer, cache: ResponseCache
) -> RunEstimate:
    requests = list(requests)
    stored = list(cache.metadata())
    if not isinstance(analyzer, TwoStageExtractor):
        single = _stage_of(analyzer)
        misses = sum(single.lookup(request) is None for request in requests)
        return RunEstimate(
            [_price("extract", single, len(requests), misses, stored)], unpriced_items=0
        )

    screen, extract = _stage_of(analyzer.screen), _stage_of(analyzer.extract)
    screen_misses, unpriced = 0, 0
    window_calls, window_misses = 0, 0
    for request in requests:
        screened = screen.lookup(request)
        if screened is None:
            screen_misses += 1
            unpriced += 1
            continue
        flagged = flagged_turns(screened, analyzer.flag_labels)
        for start, end in windows(flagged, analyzer.context_turns):
            window_calls += 1
            if extract.lookup(window_request(request, start, end)) is None:
                window_misses += 1
    return RunEstimate(
        [
            _price("screen", screen, len(requests), screen_misses, stored),
            _price("extract", extract, window_calls, window_misses, stored),
        ],
        unpriced_items=unpriced,
    )


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def render_estimate(estimate: RunEstimate, prompt_version: str) -> list[str]:
    lines = [f"estimate for prompt {prompt_version} (no model calls made):"]
    for stage in estimate.stages:
        line = (
            f"  {stage.stage} {stage.model}: {_count(stage.calls, 'call', 'calls')}, "
            f"{_count(stage.misses, 'miss', 'misses')}, est. {_usd(stage.cost_usd)}"
        )
        lines.append(f"{line} ({stage.note})" if stage.note and stage.misses else line)
    if estimate.unpriced_items:
        lines.append(
            f"  note: {estimate.unpriced_items} items have an uncached screen, so their extract "
            "windows are not priced; the total is a lower bound"
        )
    lines.append(
        f"total: {estimate.misses} of {estimate.calls} calls miss the cache, "
        f"est. {_usd(estimate.cost_usd)}"
    )
    return lines
