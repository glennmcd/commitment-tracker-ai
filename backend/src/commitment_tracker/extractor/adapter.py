"""The model boundary: one request in, one reply out. The Anthropic SDK lives behind it.

The adapter does no validation: it returns the reply's JSON text and lets the extractor validate it,
so a failed reply can be retried with its own assistant content appended unchanged. Transport
failures surface as `ModelUnavailable`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    # Text for user turns; for an assistant turn, the reply's content blocks exactly as returned.
    content: str | Sequence[object]


@dataclass(frozen=True)
class ModelRequest:
    system: str
    messages: tuple[Message, ...]
    output_model: type[BaseModel]


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass(frozen=True)
class ModelReply:
    text: str  # the JSON document, or whatever text came back
    stop_reason: str  # "end_turn", "max_tokens", "refusal", ...
    served_by: str  # differs from the requested model after a refusal fallback
    usage: Usage
    latency_ms: int
    assistant_content: Sequence[object]  # opaque; appended unchanged on retry
    refusal_category: str | None = None


class ModelAdapter(Protocol):
    model: str

    async def complete(self, request: ModelRequest) -> ModelReply: ...
