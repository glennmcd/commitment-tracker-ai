"""The adapter protocol, exercised through the fake that the extractor and API tests use."""

import asyncio

import pytest

from commitment_tracker.extractor.adapter import Message, ModelAdapter, ModelRequest
from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.model_output import ModelOutput
from tests.fakes import FakeAdapter, reply


def request(text: str = "hello") -> ModelRequest:
    return ModelRequest(
        system="system prompt",
        messages=(Message(role="user", content=text),),
        output_model=ModelOutput,
    )


def test_fake_satisfies_the_protocol() -> None:
    adapter: ModelAdapter = FakeAdapter(reply(ModelOutput(spans=[])))
    result = asyncio.run(adapter.complete(request()))
    assert ModelOutput.model_validate_json(result.text) == ModelOutput(spans=[])
    assert result.stop_reason == "end_turn"


def test_fake_returns_replies_in_order_and_records_requests() -> None:
    adapter = FakeAdapter(reply("first"), reply("second"))
    first = asyncio.run(adapter.complete(request("a")))
    second = asyncio.run(adapter.complete(request("b")))
    assert (first.text, second.text) == ("first", "second")
    assert [r.messages[0].content for r in adapter.requests] == ["a", "b"]


def test_fake_raises_scripted_errors() -> None:
    adapter = FakeAdapter(ModelUnavailable("rate limited"))
    with pytest.raises(ModelUnavailable):
        asyncio.run(adapter.complete(request()))


def test_retry_messages_carry_the_assistant_content_unchanged() -> None:
    first = reply("not json")
    retry = ModelRequest(
        system="system prompt",
        messages=(
            Message(role="user", content="transcript"),
            Message(role="assistant", content=first.assistant_content),
            Message(role="user", content="fix these errors"),
        ),
        output_model=ModelOutput,
    )
    assert retry.messages[1].content is first.assistant_content
