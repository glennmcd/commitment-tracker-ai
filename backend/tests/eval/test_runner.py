"""Running the extractor over a dataset: bounded concurrency, cache warm-up, per-item failures."""

import asyncio
import re
from pathlib import Path

from commitment_tracker.evaluation.cache import ResponseCache
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.evaluation.runner import run_items
from commitment_tracker.extractor.adapter import ModelReply, ModelRequest
from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.model_output import ModelOutput
from commitment_tracker.extractor.prompt import load_prompt
from tests.eval.builders import exp, item
from tests.fakes import FunctionAdapter, reply

TURN = re.compile(r'<turn index="(\d+)" speaker="[^"]*">(.*?)</turn>')
ITEMS = [
    item(f"i{n}", [f"Statement number {n}."], [exp(0, "NONE", f"Statement number {n}.")])
    for n in range(6)
]


def all_none(request: ModelRequest) -> ModelReply | Exception:
    """Labels every turn NONE, quoting it in full; fails for turns containing FAIL."""
    text = str(request.messages[0].content)
    if "FAIL" in text:
        return ModelUnavailable("RateLimitError (HTTP 429)")
    spans = [
        {
            "turn_index": int(index),
            "label": "NONE",
            "owner": None,
            "recipient": None,
            "action": None,
            "due": {"raw": None, "precision_hint": "none"},
            "condition": None,
            "confidence": 0.9,
            "quote": quote,
            "rationale": "Nothing is promised.",
            "ambiguous": False,
        }
        for index, quote in TURN.findall(text)
    ]
    return reply(ModelOutput.model_validate({"spans": spans}))


def extractor(adapter: FunctionAdapter) -> Extractor:
    return Extractor(adapter, load_prompt("v1"))


def run(
    adapter: FunctionAdapter, cache: ResponseCache | None = None, concurrency: int = 2
) -> list[ItemResult]:
    return asyncio.run(run_items(ITEMS, extractor(adapter), cache=cache, concurrency=concurrency))


def test_returns_one_result_per_item_in_order() -> None:
    results = run(FunctionAdapter(all_none))
    assert [r.item.id for r in results] == [i.id for i in ITEMS]
    assert all(r.response is not None and r.error is None for r in results)


def test_concurrency_is_bounded() -> None:
    adapter = FunctionAdapter(all_none, delay=0.02)
    run(adapter, concurrency=2)
    assert adapter.max_in_flight == 2


def test_first_item_runs_alone_to_warm_the_prompt_cache() -> None:
    adapter = FunctionAdapter(all_none, delay=0.01)
    run(adapter, concurrency=4)
    assert adapter.events[:2] == ["start", "end"]


def test_cached_items_skip_the_model(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    first = FunctionAdapter(all_none)
    run(first, cache)
    assert first.calls == len(ITEMS)

    second = FunctionAdapter(all_none)
    results = run(second, cache)
    assert second.calls == 0
    assert all(r.cached for r in results)


def test_a_failed_item_is_recorded_and_the_run_continues(tmp_path: Path) -> None:
    items = [*ITEMS[:2], item("bad", ["FAIL here."], [exp(0, "NONE", "FAIL here.")])]
    cache = ResponseCache(tmp_path)
    results = asyncio.run(
        run_items(items, extractor(FunctionAdapter(all_none)), cache=cache, concurrency=2)
    )
    assert [r.error for r in results] == [None, None, "model_unavailable"]
    assert results[2].response is None
    assert len(list(tmp_path.glob("*.json"))) == 2  # failures are not cached
