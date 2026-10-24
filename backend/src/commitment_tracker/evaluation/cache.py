"""Cached extractor responses for evaluation runs, one JSON file per key.

The key hashes the request, the model, the prompt text and the effort, so a rerun only calls the
model for what changed. Only successful responses are stored; a corrupt file reads as a miss.

`CachedAnalyzer` puts the cache around one extractor. The two-stage pipeline gets one per stage, so
its screen shares keys with a plain Haiku run and costs nothing after one. Misses are counted per
evaluation item through a context variable, which is how the runner knows an item was fully cached.
"""

import hashlib
import json
from contextvars import ContextVar
from pathlib import Path

from pydantic import ValidationError

from commitment_tracker.extractor.adapter import ModelReply, ModelRequest
from commitment_tracker.extractor.analyzer import Configuration
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse

# backend/src/commitment_tracker/evaluation/cache.py -> backend/eval/.cache (git-ignored)
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "eval" / ".cache"
COMPUTED_FIELDS = {"spans": {"__all__": {"in_ledger", "soft"}}}
# The model never sees turn timestamps, so they stay out of the key and existing keys stay valid.
TIMESTAMP_FIELDS = {"transcript": {"__all__": {"start_ms", "end_ms"}}}


def cache_key(request: AnalyzeRequest, *, model: str, prompt_sha256: str, effort: str) -> str:
    material = {
        "request": request.model_dump(mode="json", exclude=TIMESTAMP_FIELDS),
        "model": model,
        "prompt_sha256": prompt_sha256,
        "effort": effort,
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CacheMiss(Exception):
    """An offline run needed a response the cache doesn't have."""


class OfflineAdapter:
    """Stands in for the model on `--offline` runs: it holds no key and any call is a cache miss.

    The CLI checks every item is cached before running, so this only fires if that check and the
    runner's keys ever disagree.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    async def complete(self, request: ModelRequest) -> ModelReply:
        raise CacheMiss(f"no cached response for model {self.model}")


class ResponseCache:
    def __init__(self, directory: Path = DEFAULT_CACHE_DIR) -> None:
        self.directory = directory

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> AnalyzeResponse | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            return AnalyzeResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError:
            return None

    def put(self, key: str, response: AnalyzeResponse) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        # Ledger flags are computed from the label, so they aren't stored.
        self._path(key).write_text(
            response.model_dump_json(exclude=COMPUTED_FIELDS, indent=2), encoding="utf-8"
        )


# The keys missed while analyzing the current item; the runner sets a fresh list per item.
CACHE_MISSES: ContextVar[list[str] | None] = ContextVar("cache_misses", default=None)


class CachedAnalyzer:
    """An extractor behind the response cache. With no cache, every call is a miss."""

    def __init__(self, extractor: Extractor, cache: ResponseCache | None, effort: str) -> None:
        self.extractor = extractor
        self.cache = cache
        self.effort = effort

    def key(self, request: AnalyzeRequest) -> str:
        return cache_key(
            request,
            model=self.extractor.adapter.model,
            prompt_sha256=self.extractor.prompt.sha256,
            effort=self.effort,
        )

    def is_cached(self, request: AnalyzeRequest) -> bool:
        return self.cache is not None and self.cache.get(self.key(request)) is not None

    def describe(self) -> Configuration:
        return self.extractor.describe()

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        key = self.key(request)
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            return hit
        misses = CACHE_MISSES.get()
        if misses is not None:
            misses.append(key)
        response = await self.extractor.analyze(request)
        if self.cache is not None:
            self.cache.put(key, response)
        return response
