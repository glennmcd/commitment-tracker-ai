"""The two-stage pipeline (ADR 0011): a cheap model screens, the strong model judges flagged turns.

1. Screen: the screen analyzer runs the full extraction on the whole transcript.
2. Flag: every turn where the screen returned a span labelled in `flag_labels` (by default anything
   but NONE) is flagged.
3. Extract: each flagged turn, with up to `context_turns` preceding turns, forms a window;
   overlapping or touching windows merge. Each window goes to the extract analyzer as its own
   transcript, and its spans are mapped back to the original turn indices. Spans on context-only
   turns are discarded: context is there to inform the flagged turn, not to be judged again.
4. Merge: extract spans replace the screen's on flagged turns; the screen's spans stand elsewhere.

Both stages use the same prompt, so there is no second prompt to tune. Logs carry counts only.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from commitment_tracker.extractor.analyzer import Analyzer, Configuration
from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse, Label, Metadata, Span

logger = logging.getLogger(__name__)

NAME = "two-stage"
NON_NONE = frozenset(label for label in Label if label is not Label.NONE)


@dataclass(frozen=True)
class StageUsage:
    stage: str  # "screen" or "extract"
    model: str  # the model that answered (last call, for a multi-window extract stage)
    calls: int
    latency_ms: int  # wall clock of the stage; windows run concurrently
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float | None


@dataclass(frozen=True)
class TwoStageResult:
    response: AnalyzeResponse
    stages: list[StageUsage]
    flagged_turns: list[int]
    windows: list[tuple[int, int]]  # inclusive turn ranges sent to the extract stage


def windows(flagged: list[int], context_turns: int) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for turn in sorted(flagged):
        start = max(0, turn - context_turns)
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], turn)
        else:
            merged.append((start, turn))
    return merged


def _usage(stage: str, responses: list[AnalyzeResponse], latency_ms: int) -> StageUsage:
    costs = [r.metadata.cost_usd for r in responses]
    return StageUsage(
        stage=stage,
        model=responses[-1].metadata.served_by,
        calls=len(responses),
        latency_ms=latency_ms,
        input_tokens=sum(r.metadata.input_tokens for r in responses),
        output_tokens=sum(r.metadata.output_tokens for r in responses),
        cache_creation_input_tokens=sum(r.metadata.cache_creation_input_tokens for r in responses),
        cache_read_input_tokens=sum(r.metadata.cache_read_input_tokens for r in responses),
        cost_usd=None if None in costs else sum(c for c in costs if c is not None),
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


class TwoStageExtractor:
    def __init__(
        self,
        screen: Analyzer,
        extract: Analyzer,
        *,
        flag_labels: frozenset[Label] = NON_NONE,
        context_turns: int = 2,
    ) -> None:
        self.screen = screen
        self.extract = extract
        self.flag_labels = flag_labels
        self.context_turns = context_turns

    def describe(self) -> Configuration:
        screen, extract = self.screen.describe(), self.extract.describe()
        return Configuration(
            name=NAME,
            stages={"screen": screen.stages["extract"], "extract": extract.stages["extract"]},
            prompt_version=extract.prompt_version,
            prompt_sha256=extract.prompt_sha256,
            effort=extract.effort,
        )

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        return (await self.analyze_detailed(request)).response

    async def _window(self, request: AnalyzeRequest, start: int, end: int) -> AnalyzeResponse:
        sub = request.model_copy(update={"transcript": request.transcript[start : end + 1]})
        response = await self.extract.analyze(sub)
        spans = [
            span.model_copy(update={"turn_index": span.turn_index + start})
            for span in response.spans
        ]
        return response.model_copy(update={"spans": spans})

    async def analyze_detailed(self, request: AnalyzeRequest) -> TwoStageResult:
        started = time.perf_counter()
        screened = await self.screen.analyze(request)
        stages = [_usage("screen", [screened], _elapsed_ms(started))]
        flagged = sorted({s.turn_index for s in screened.spans if s.label in self.flag_labels})
        spans_by_window = windows(flagged, self.context_turns)

        extracted: list[AnalyzeResponse] = []
        if spans_by_window:
            extract_started = time.perf_counter()
            extracted = list(
                await asyncio.gather(
                    *(self._window(request, start, end) for start, end in spans_by_window)
                )
            )
            stages.append(_usage("extract", extracted, _elapsed_ms(extract_started)))

        keep = set(flagged)
        spans: list[Span] = [s for s in screened.spans if s.turn_index not in keep]
        spans += [s for r in extracted for s in r.spans if s.turn_index in keep]
        spans.sort(key=lambda span: span.turn_index)
        logger.info(
            "two_stage turns=%d flagged=%d windows=%d",
            len(request.transcript),
            len(flagged),
            len(spans_by_window),
        )
        responses = [screened, *extracted]
        costs = [stage.cost_usd for stage in stages]
        metadata = Metadata(
            model=NAME,
            served_by=(extracted[-1] if extracted else screened).metadata.served_by,
            prompt_version=screened.metadata.prompt_version,
            latency_ms=_elapsed_ms(started),
            input_tokens=sum(stage.input_tokens for stage in stages),
            output_tokens=sum(stage.output_tokens for stage in stages),
            cache_creation_input_tokens=sum(s.cache_creation_input_tokens for s in stages),
            cache_read_input_tokens=sum(s.cache_read_input_tokens for s in stages),
            cost_usd=None if None in costs else sum(c for c in costs if c is not None),
            attempts=max(r.metadata.attempts for r in responses),
            dropped_quotes=sum(r.metadata.dropped_quotes for r in responses),
        )
        return TwoStageResult(
            response=AnalyzeResponse(spans=spans, metadata=metadata),
            stages=stages,
            flagged_turns=flagged,
            windows=spans_by_window,
        )
