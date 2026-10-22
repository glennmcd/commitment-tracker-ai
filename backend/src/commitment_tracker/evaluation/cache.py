"""Cached extractor responses for evaluation runs, one JSON file per key.

The key hashes the request, the model, the prompt text and the effort, so a rerun only calls the
model for what changed. Only successful responses are stored; a corrupt file reads as a miss.
"""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse

# backend/src/commitment_tracker/evaluation/cache.py -> backend/eval/.cache (git-ignored)
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "eval" / ".cache"
COMPUTED_FIELDS = {"spans": {"__all__": {"in_ledger", "soft"}}}


def cache_key(request: AnalyzeRequest, *, model: str, prompt_sha256: str, effort: str) -> str:
    material = {
        "request": request.model_dump(mode="json"),
        "model": model,
        "prompt_sha256": prompt_sha256,
        "effort": effort,
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
