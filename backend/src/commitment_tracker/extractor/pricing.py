"""Estimated request cost from token usage.

Prices in USD per million tokens, from platform.claude.com/docs/en/about-claude/pricing (checked
2026-10-21). Cache writes use the 5-minute rate. An unknown model has no price rather than a guess.
"""

from dataclasses import dataclass

from commitment_tracker.extractor.adapter import Usage


@dataclass(frozen=True)
class Rates:
    input: float
    cache_write: float
    cache_read: float
    output: float


@dataclass(frozen=True)
class Price:
    standard: Rates
    long_prompt: Rates | None = None  # applies above `long_prompt_tokens` prompt tokens
    long_prompt_tokens: int = 0


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(Rates(input=4.00, cache_write=5.00, cache_read=0.20, output=20.00)),
    "claude-sonnet-5-5": Price(Rates(input=2.00, cache_write=2.50, cache_read=0.10, output=10.00)),
    "claude-haiku-5-5": Price(
        Rates(input=0.10, cache_write=0.125, cache_read=0.01, output=0.50),
        long_prompt=Rates(input=0.50, cache_write=0.625, cache_read=0.05, output=2.50),
        long_prompt_tokens=100_000,
    ),
}


def cost_usd(model: str, usage: Usage) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    prompt_tokens = (
        usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
    )
    rates = price.standard
    if price.long_prompt is not None and prompt_tokens > price.long_prompt_tokens:
        rates = price.long_prompt
    return (
        usage.input_tokens * rates.input
        + usage.cache_creation_input_tokens * rates.cache_write
        + usage.cache_read_input_tokens * rates.cache_read
        + usage.output_tokens * rates.output
    ) / 1_000_000
