"""The extraction pipeline: one model call per transcript, validated, with one retry.

The model only proposes. Its reply is validated into `ModelOutput`, every span is checked against
the transcript and converted to a `Span` with the due date resolved by code, and an invalid reply is
retried once with the errors appended. Spans whose quote is not in their turn are dropped and logged
as hallucinations. Logs and retry messages carry field paths, counts and ids, never transcript text.
"""

import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from commitment_tracker.extractor.adapter import Message, ModelAdapter, ModelReply, ModelRequest
from commitment_tracker.extractor.analyzer import Configuration
from commitment_tracker.extractor.dates import resolve_due
from commitment_tracker.extractor.errors import ModelOutputInvalid, ModelRefused
from commitment_tracker.extractor.model_output import ModelOutput, ModelSpan
from commitment_tracker.extractor.pricing import cost_usd
from commitment_tracker.extractor.prompt import Prompt, build_user_message
from commitment_tracker.schemas import AnalyzeRequest, AnalyzeResponse, Due, Metadata, Span

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # the first reply plus one retry; Metadata.attempts allows the same range

RETRY_INSTRUCTION = (
    "Your previous reply could not be used:\n{errors}\n\n"
    "Reply again with the complete JSON for the whole transcript, following the schema and the "
    "rules. Copy every quote exactly from the turn at its turn_index."
)


@dataclass(frozen=True)
class _Checked:
    spans: list[Span]
    errors: list[str]


def _format_validation_error(error: ValidationError, prefix: str = "") -> list[str]:
    lines = []
    for detail in error.errors(include_url=False, include_input=False):
        path = ".".join(str(part) for part in (prefix, *detail["loc"]) if part != "")
        lines.append(f"{path}: {detail['msg']}" if path else detail["msg"])
    return lines


def _to_span(model_span: ModelSpan, request: AnalyzeRequest) -> Span:
    raw = model_span.due.raw if model_span.due.raw and model_span.due.raw.strip() else None
    resolved = resolve_due(raw, request.call_date, model_span.due.precision_hint)
    return Span.model_validate(
        {
            **model_span.model_dump(exclude={"due"}),
            "due": Due(raw=raw, resolved=resolved.resolved, precision=resolved.precision),
        }
    )


def _check(reply: ModelReply, request: AnalyzeRequest) -> _Checked:
    """Validate a reply into spans, or say exactly which fields are wrong."""
    if reply.stop_reason == "refusal":
        raise ModelRefused(reply.refusal_category)
    if reply.stop_reason == "max_tokens":
        return _Checked([], ["the reply was cut off at max_tokens; keep the JSON compact"])
    try:
        output = ModelOutput.model_validate_json(reply.text)
    except ValidationError as error:
        return _Checked([], _format_validation_error(error))

    spans: list[Span] = []
    errors: list[str] = []
    turns = len(request.transcript)
    for index, model_span in enumerate(output.spans):
        if model_span.turn_index >= turns:
            errors.append(
                f"spans.{index}.turn_index: {model_span.turn_index} is not a turn "
                f"(the transcript has {turns} turns, numbered from 0)"
            )
            continue
        try:
            spans.append(_to_span(model_span, request))
        except ValidationError as error:
            errors.extend(_format_validation_error(error, prefix=f"spans.{index}"))
    return _Checked(spans, errors)


def _quoted(span: Span, request: AnalyzeRequest) -> bool:
    return span.quote in request.transcript[span.turn_index].text


class Extractor:
    def __init__(self, adapter: ModelAdapter, prompt: Prompt, *, name: str | None = None) -> None:
        self.adapter = adapter
        self.prompt = prompt
        self.name = name or adapter.model

    def describe(self) -> Configuration:
        return Configuration(
            name=self.name,
            stages={"extract": self.adapter.model},
            prompt_version=self.prompt.version,
            prompt_sha256=self.prompt.sha256,
            effort=getattr(self.adapter, "effort", None),
        )

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        started = time.perf_counter()
        messages: tuple[Message, ...] = (Message("user", build_user_message(request)),)
        replies: list[ModelReply] = []

        while True:
            reply = await self.adapter.complete(
                ModelRequest(system=self.prompt.system, messages=messages, output_model=ModelOutput)
            )
            replies.append(reply)
            checked = _check(reply, request)
            if not checked.errors:
                break
            logger.info(
                "model_output_invalid attempt=%d errors=%d", len(replies), len(checked.errors)
            )
            if len(replies) == MAX_ATTEMPTS:
                raise ModelOutputInvalid("; ".join(checked.errors))
            correction = RETRY_INSTRUCTION.format(
                errors="\n".join(f"- {e}" for e in checked.errors)
            )
            messages = (
                *messages,
                Message("assistant", reply.assistant_content),
                Message("user", correction),
            )

        kept: list[Span] = []
        for span in checked.spans:
            if _quoted(span, request):
                kept.append(span)
            else:
                logger.warning(
                    "hallucinated_quote turn=%d quote_length=%d label=%s",
                    span.turn_index,
                    len(span.quote),
                    span.label,
                )
        kept.sort(key=lambda span: span.turn_index)

        return AnalyzeResponse(
            spans=kept,
            metadata=self._metadata(
                replies,
                round((time.perf_counter() - started) * 1000),
                len(checked.spans) - len(kept),
            ),
        )

    def _metadata(self, replies: list[ModelReply], latency_ms: int, dropped: int) -> Metadata:
        costs = [cost_usd(r.served_by, r.usage) for r in replies]
        return Metadata(
            model=self.adapter.model,
            served_by=replies[-1].served_by,
            prompt_version=self.prompt.version,
            latency_ms=latency_ms,
            input_tokens=sum(r.usage.input_tokens for r in replies),
            output_tokens=sum(r.usage.output_tokens for r in replies),
            cache_creation_input_tokens=sum(r.usage.cache_creation_input_tokens for r in replies),
            cache_read_input_tokens=sum(r.usage.cache_read_input_tokens for r in replies),
            cost_usd=None if None in costs else sum(c for c in costs if c is not None),
            attempts=len(replies),
            dropped_quotes=dropped,
        )
