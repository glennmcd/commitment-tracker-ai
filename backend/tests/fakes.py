"""Test doubles for the model adapter: scripted replies, recorded requests, no network."""

from collections import deque

from commitment_tracker.extractor.adapter import ModelReply, ModelRequest, Usage
from commitment_tracker.extractor.model_output import ModelOutput

DEFAULT_USAGE = Usage(
    input_tokens=200,
    output_tokens=400,
    cache_creation_input_tokens=0,
    cache_read_input_tokens=2500,
)


def reply(
    output: ModelOutput | str,
    *,
    stop_reason: str = "end_turn",
    served_by: str = "fake-model",
    usage: Usage = DEFAULT_USAGE,
    latency_ms: int = 50,
    refusal_category: str | None = None,
) -> ModelReply:
    """A scripted reply; `output` is a parsed output or raw text (for invalid replies)."""
    text = output if isinstance(output, str) else output.model_dump_json()
    return ModelReply(
        text=text,
        stop_reason=stop_reason,
        served_by=served_by,
        usage=usage,
        latency_ms=latency_ms,
        assistant_content=({"type": "text", "text": text},),
        refusal_category=refusal_category,
    )


class FakeAdapter:
    """Returns scripted replies in order (or raises scripted errors) and records every request."""

    def __init__(self, *replies: ModelReply | Exception, model: str = "fake-model") -> None:
        self.model = model
        self._replies: deque[ModelReply | Exception] = deque(replies)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        if not self._replies:
            raise AssertionError("FakeAdapter has no scripted reply left")
        next_reply = self._replies.popleft()
        if isinstance(next_reply, Exception):
            raise next_reply
        return next_reply
