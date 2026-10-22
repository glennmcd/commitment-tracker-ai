"""Runs the extractor over evaluation items with bounded concurrency and a response cache.

The first uncached item runs alone so it writes the prompt cache; the rest then fan out, so
concurrent first requests don't each pay for a cache write. A failed item is recorded with its error
code and the run continues; failures are not cached.
"""

import asyncio
import logging

from commitment_tracker.evaluation.cache import ResponseCache, cache_key
from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.extractor.errors import ExtractionError
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.schemas import AnalyzeRequest

logger = logging.getLogger(__name__)


def request_for(item: EvalItem) -> AnalyzeRequest:
    return AnalyzeRequest(transcript=item.turns, call_date=item.call_date)


async def run_items(
    items: list[EvalItem],
    extractor: Extractor,
    *,
    cache: ResponseCache | None = None,
    concurrency: int = 4,
    effort: str = "medium",
) -> list[ItemResult]:
    def key(item: EvalItem) -> str:
        return cache_key(
            request_for(item),
            model=extractor.adapter.model,
            prompt_sha256=extractor.prompt.sha256,
            effort=effort,
        )

    results: dict[str, ItemResult] = {}
    pending: list[EvalItem] = []
    for item in items:
        cached = cache.get(key(item)) if cache else None
        if cached is not None:
            results[item.id] = ItemResult(item, cached, error=None, cached=True)
        else:
            pending.append(item)

    async def run_one(item: EvalItem) -> None:
        try:
            response = await extractor.analyze(request_for(item))
        except ExtractionError as error:
            # Extraction errors carry field paths and SDK class names, never transcript text.
            logger.warning("eval_item_failed id=%s code=%s detail=%s", item.id, error.code, error)
            results[item.id] = ItemResult(item, None, error=error.code, cached=False)
            return
        if cache:
            cache.put(key(item), response)
        results[item.id] = ItemResult(item, response, error=None, cached=False)

    if pending:
        await run_one(pending[0])  # writes the prompt cache before the fan-out
        limit = asyncio.Semaphore(concurrency)

        async def bounded(item: EvalItem) -> None:
            async with limit:
                await run_one(item)

        await asyncio.gather(*(bounded(item) for item in pending[1:]))

    return [results[item.id] for item in items]
