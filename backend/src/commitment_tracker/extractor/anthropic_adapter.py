"""The one real model adapter: Claude through the Anthropic Python SDK.

Design: docs/plans/part-1-extraction-call.md. One non-streaming request per call with the system
prompt cached, the output schema sent as structured output (forced tool use is rejected by Opus 5.5
and Sonnet 5.5), effort set explicitly, and server-side refusal fallback where the model supports
it. Thinking is left at each model's adaptive default; Opus 5.5 can't turn it off.
"""

import time
from typing import Any, Literal

import anthropic
from anthropic.types.beta import BetaMessage

from commitment_tracker.extractor.adapter import Message, ModelReply, ModelRequest, Usage
from commitment_tracker.extractor.errors import ModelUnavailable

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Models that accept `fallbacks: "default"`; Haiku 5.5 has no server-side fallback.
SERVER_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _message_param(message: Message) -> dict[str, Any]:
    content = message.content if isinstance(message.content, str) else list(message.content)
    return {"role": message.role, "content": content}


class AnthropicAdapter:
    def __init__(
        self,
        model: str,
        *,
        effort: Effort = "medium",
        max_tokens: int = 16_000,
        client: anthropic.AsyncAnthropic | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        # The API key comes from the environment (ANTHROPIC_API_KEY or an `ant auth` profile).
        self.client = client or anthropic.AsyncAnthropic(
            timeout=timeout_seconds, max_retries=max_retries
        )

    def build_params(self, request: ModelRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [_message_param(m) for m in request.messages],
            "output_config": {
                "effort": self.effort,
                "format": {
                    "type": "json_schema",
                    "schema": anthropic.transform_schema(request.output_model),
                },
            },
        }
        if self.model in SERVER_FALLBACK_MODELS:
            params["betas"] = [SERVER_FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def complete(self, request: ModelRequest) -> ModelReply:
        params = self.build_params(request)
        started = time.perf_counter()
        try:
            message: BetaMessage = await self.client.beta.messages.create(**params)
        except anthropic.APIStatusError as error:
            # The SDK has already retried 429s and 5xx; error text never includes the request.
            raise ModelUnavailable(f"{type(error).__name__} (HTTP {error.status_code})") from error
        except anthropic.APIConnectionError as error:
            raise ModelUnavailable(type(error).__name__) from error
        latency_ms = round((time.perf_counter() - started) * 1000)

        text = next((block.text for block in message.content if block.type == "text"), "")
        usage = message.usage
        return ModelReply(
            text=text,
            stop_reason=message.stop_reason or "unknown",
            served_by=message.model,
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
                cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            ),
            latency_ms=latency_ms,
            # Plain dicts, unchanged: thinking blocks must go back exactly as they came.
            assistant_content=tuple(block.to_dict() for block in message.content),
            refusal_category=message.stop_details.category if message.stop_details else None,
        )
