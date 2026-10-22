"""The sample clips a visitor can pick instead of recording.

The clips are WAVs under `samples/` in the audio bucket. The manifest bundled with the package
(`samples.json`) lists their ids, titles, durations and SHA-256 hashes; a job on a sample takes its
id from the stored hash, so the API never reads the clip.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

MANIFEST = Path(__file__).with_name("samples.json")


class SampleClip(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=100)
    duration_ms: int = Field(gt=0, le=60_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def key(self) -> str:
        return f"samples/{self.id}.wav"


class SampleCatalog:
    def __init__(self, clips: list[SampleClip]) -> None:
        by_id: dict[str, SampleClip] = {}
        for clip in clips:
            if clip.id in by_id:
                raise ValueError(f"duplicate sample id {clip.id}")
            by_id[clip.id] = clip
        self._by_id = by_id

    def get(self, clip_id: str) -> SampleClip | None:
        return self._by_id.get(clip_id)

    def all(self) -> list[SampleClip]:
        return list(self._by_id.values())


def load_catalog(path: Path = MANIFEST) -> SampleCatalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SampleCatalog([SampleClip.model_validate(item) for item in raw])
