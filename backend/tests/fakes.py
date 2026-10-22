"""Test doubles for the model adapter: scripted replies, recorded requests, no network."""

import asyncio
from collections import deque
from collections.abc import Callable

from commitment_tracker.extractor.adapter import ModelReply, ModelRequest, Usage
from commitment_tracker.extractor.model_output import ModelOutput
from commitment_tracker.jobs.audio_store import StoredAudio

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


class FunctionAdapter:
    """Answers each request with `answer(request)` after `delay` seconds, and tracks how many
    calls run at once. Use it when replies depend on the request rather than on call order."""

    def __init__(
        self,
        answer: Callable[[ModelRequest], ModelReply | Exception],
        *,
        delay: float = 0.0,
        model: str = "fake-model",
    ) -> None:
        self.model = model
        self.answer = answer
        self.delay = delay
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.events: list[str] = []

    async def complete(self, request: ModelRequest) -> ModelReply:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.events.append("start")
        try:
            await asyncio.sleep(self.delay)
            result = self.answer(request)
        finally:
            self.in_flight -= 1
            self.events.append("end")
        if isinstance(result, Exception):
            raise result
        return result


class FakeAudioStore:
    """An audio store over a dict of key -> (bytes, uploaded_at_ms); records deletions."""

    def __init__(self, bucket: str = "audio-bucket") -> None:
        self.bucket = bucket
        self.objects: dict[str, StoredAudio] = {}
        self.deleted: list[str] = []

    def put(self, key: str, data: bytes, uploaded_at_ms: int | None = None) -> None:
        self.objects[key] = StoredAudio(data=data, uploaded_at_ms=uploaded_at_ms)

    def read(self, key: str) -> StoredAudio | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


class FakeDispatcher:
    """Records the jobs handed to the worker, or fails when told to."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.dispatched: list[str] = []

    def dispatch(self, job_id: str) -> None:
        if self.error is not None:
            raise self.error
        self.dispatched.append(job_id)
