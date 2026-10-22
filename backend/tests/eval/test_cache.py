"""The response cache: keyed by input, model, prompt and effort; stores successful responses."""

from datetime import date
from pathlib import Path

from commitment_tracker.evaluation.cache import ResponseCache, cache_key
from commitment_tracker.schemas import AnalyzeRequest, Turn
from tests.eval.builders import pred, response

REQUEST = AnalyzeRequest(
    transcript=[Turn(speaker="seller", text="I'll send it Friday.")], call_date=date(2026, 10, 21)
)
BASE = {"model": "claude-opus-5-5", "prompt_sha256": "a" * 64, "effort": "medium"}


def key(request: AnalyzeRequest = REQUEST, **overrides: str) -> str:
    return cache_key(request, **{**BASE, **overrides})


def test_key_is_stable() -> None:
    assert key() == key()
    assert len(key()) == 64


def test_key_changes_with_each_input() -> None:
    other_text = REQUEST.model_copy(
        update={"transcript": [Turn(speaker="seller", text="I'll send it Monday.")]}
    )
    other_date = REQUEST.model_copy(update={"call_date": date(2026, 10, 22)})
    keys = {
        key(),
        key(other_text),
        key(other_date),
        key(model="claude-haiku-5-5"),
        key(prompt_sha256="b" * 64),
        key(effort="low"),
    }
    assert len(keys) == 6


def test_round_trip(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "cache")
    stored = response(pred(0, "HEDGED", "I'll send it Friday."))
    cache.put(key(), stored)
    assert cache.get(key()) == stored


def test_miss_returns_none(tmp_path: Path) -> None:
    assert ResponseCache(tmp_path).get(key()) is None


def test_corrupt_entry_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    (tmp_path / f"{key()}.json").write_text("{broken", encoding="utf-8")
    assert cache.get(key()) is None
