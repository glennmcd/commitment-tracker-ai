"""Estimated cost from token usage, at the prices on the Anthropic pricing page (checked
2026-10-21): base input, 5-minute cache writes, cache reads and output, per million tokens.
"""

import pytest

from commitment_tracker.extractor.adapter import Usage
from commitment_tracker.extractor.pricing import cost_usd


def usage(inp: int = 0, out: int = 0, write: int = 0, read: int = 0) -> Usage:
    return Usage(
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=write,
        cache_read_input_tokens=read,
    )


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # 1M of each category: input + cache write + cache read + output
        ("claude-opus-5-5", 4.00 + 5.00 + 0.20 + 20.00),
        ("claude-sonnet-5-5", 2.00 + 2.50 + 0.10 + 10.00),
    ],
)
def test_prices_each_token_category(model: str, expected: float) -> None:
    million = 1_000_000
    assert cost_usd(model, usage(million, million, million, million)) == pytest.approx(expected)


def test_typical_eval_item_on_opus() -> None:
    # 200 fresh input tokens, 2,500 cached system tokens read, 1,000 output tokens.
    expected = (200 * 4.00 + 2_500 * 0.20 + 1_000 * 20.00) / 1_000_000
    assert cost_usd("claude-opus-5-5", usage(200, 1_000, read=2_500)) == pytest.approx(expected)


def test_haiku_short_prompt_rates() -> None:
    cost = cost_usd("claude-haiku-5-5", usage(50_000, 10_000, write=20_000, read=30_000))
    expected = (50_000 * 0.10 + 20_000 * 0.125 + 30_000 * 0.01 + 10_000 * 0.50) / 1_000_000
    assert cost == pytest.approx(expected)


def test_haiku_long_prompt_rates_apply_over_100k_prompt_tokens() -> None:
    # The threshold counts the whole prompt: uncached input plus cache writes and reads.
    cost = cost_usd("claude-haiku-5-5", usage(60_000, 10_000, write=20_000, read=30_000))
    expected = (60_000 * 0.50 + 20_000 * 0.625 + 30_000 * 0.05 + 10_000 * 2.50) / 1_000_000
    assert cost == pytest.approx(expected)


def test_zero_usage_costs_nothing() -> None:
    assert cost_usd("claude-sonnet-5-5", usage()) == 0


@pytest.mark.parametrize("model", ["fake-model", "claude-opus-5-5-20260401", ""])
def test_unknown_model_has_no_price(model: str) -> None:
    assert cost_usd(model, usage(100, 100)) is None
