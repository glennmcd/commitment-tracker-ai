"""Runs an analyzer over evaluation items with bounded concurrency and a response cache.

A plain `Extractor` is put behind the cache here; a two-stage pipeline arrives with a cache around
each stage already (the factory's `wrap`). The first uncached item runs alone so it writes the
prompt cache; the rest then fan out, so concurrent first requests don't each pay for a cache write.
A failed item is recorded with its error code and the run continues; failures are not cached.
"""

import asyncio
import logging
from collections.abc import Callable

from commitment_tracker.evaluation.cache import (
    CACHE_MISSES,
    CachedAnalyzer,
    ResponseCache,
)
from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.extractor.analyzer import Analyzer
from commitment_tracker.extractor.errors import ExtractionError
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.two_stage import TwoStageExtractor
from commitment_tracker.schemas import AnalyzeRequest

logger = logging.getLogger(__name__)


def request_for(item: EvalItem) -> AnalyzeRequest:
    return AnalyzeRequest(transcript=item.turns, call_date=item.call_date)


def _peek(analyzer: Analyzer) -> Callable[[AnalyzeRequest], bool]:
    """Whether an item will (probably) come from the cache: for two-stage, its screen does."""
    first = analyzer.screen if isinstance(analyzer, TwoStageExtractor) else analyzer
    if isinstance(first, CachedAnalyzer):
        return first.is_cached
    return lambda _: False


async def run_items(
    items: list[EvalItem],
    analyzer: Analyzer,
    *,
    cache: ResponseCache | None = None,
    concurrency: int = 4,
    effort: str = "medium",
) -> list[ItemResult]:
    if isinstance(analyzer, Extractor):
        analyzer = CachedAnalyzer(analyzer, cache, effort)
    peek = _peek(analyzer)
    results: dict[str, ItemResult] = {}

    async def run_one(item: EvalItem) -> None:
        misses: list[str] = []
        token = CACHE_MISSES.set(misses)
        try:
            if isinstance(analyzer, TwoStageExtractor):
                detailed = await analyzer.analyze_detailed(request_for(item))
                response, stages, flagged = (
                    detailed.response,
                    detailed.stages,
                    detailed.flagged_turns,
                )
            else:
                response, stages, flagged = await analyzer.analyze(request_for(item)), None, None
        except ExtractionError as error:
            # Extraction errors carry field paths and SDK class names, never transcript text.
            logger.warning("eval_item_failed id=%s code=%s detail=%s", item.id, error.code, error)
            results[item.id] = ItemResult(item, None, error=error.code, cached=False)
            return
        finally:
            CACHE_MISSES.reset(token)
        results[item.id] = ItemResult(
            item, response, error=None, cached=not misses, stages=stages, flagged_turns=flagged
        )

    cached = [item for item in items if peek(request_for(item))]
    pending = [item for item in items if item not in cached]
    limit = asyncio.Semaphore(concurrency)

    async def bounded(item: EvalItem) -> None:
        async with limit:
            await run_one(item)

    await asyncio.gather(*(bounded(item) for item in cached))
    if pending:
        await run_one(pending[0])  # writes the prompt cache before the fan-out
        await asyncio.gather(*(bounded(item) for item in pending[1:]))

    return [results[item.id] for item in items]
