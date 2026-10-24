"""What evaluation and the API need from an extraction pipeline, single-model or two-stage.

An analyzer turns a request into a validated response, and describes itself so a report can name
exactly what ran: the configuration name, the model behind each stage, the prompt and the effort.
"""

from dataclasses import dataclass
from typing import Protocol

from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse


@dataclass(frozen=True)
class Configuration:
    name: str  # "opus", "two-stage", or a bare model id
    stages: dict[str, str]  # stage -> model id: {"extract": ...} or {"screen": ..., "extract": ...}
    prompt_version: str
    prompt_sha256: str
    effort: str | None


class Analyzer(Protocol):
    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse: ...

    def describe(self) -> Configuration: ...
