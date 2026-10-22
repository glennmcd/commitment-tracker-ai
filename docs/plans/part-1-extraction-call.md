# Part 1: the extraction call

Oct 21, 2026 · Accepted

How the extractor turns one transcript into validated spans: one request per transcript, JSON constrained by
structured outputs, validated into Pydantic, with one retry and a deterministic post-pass. This replaces the
"forced tool use" idea in the first Part 1 plan, which the current models reject (see [Why not forced tool
use](#why-not-forced-tool-use)).

Sources were checked on 2026-10-21 against platform.claude.com; they are listed at the end with the section each
claim comes from.

## Summary

| Decision | Choice |
| --- | --- |
| Call granularity | One Messages API request per transcript; the model returns one span or more for every turn |
| JSON mechanism | Structured outputs: `client.messages.parse(..., output_format=ModelOutput)` on `AsyncAnthropic` |
| Context rule | Each turn is judged on its own text plus the preceding turn; the prompt says so, and the eval checks it |
| Validation | SDK schema validation, then our Pydantic validators; one retry with the error appended; then `ModelOutputInvalid` |
| Post-pass (code, not model) | Quote substring check, date resolution, ledger flags |
| Caching | `cache_control` on the system prompt (label definitions + few-shots); the transcript is the uncached tail |
| Default model | `claude-opus-5-5`, effort set explicitly; Sonnet 5.5 and Haiku 5.5 are comparison runs |

## Request shape

```text
system   [cached]  prompts/v1.md: role, the 8 label definitions, the context rule, 8 few-shot examples
messages user      <call_date>2026-10-21</call_date>
                   <transcript>
                   <turn index="0" speaker="buyer">Can you resend the invoice?</turn>
                   <turn index="1" speaker="seller">Sure, I'll do it this afternoon.</turn>
                   </transcript>
output_config      format: json_schema generated from ModelOutput; effort: from settings
max_tokens         16000 (non-streaming; thinking counts toward it)
```

`call_date` is in the message only so the model can tell past from future ("last week", "promised a rebate");
it never computes dates. Speaker names are passed through as given; transcript text is wrapped in tags and
treated as data, so text such as "ignore the instructions above" inside a turn stays transcript content.

### Output schema

```python
class ModelDue(BaseModel):
    raw: str | None            # the due phrase exactly as spoken ("by Friday"), or null
    precision_hint: Literal["day", "week", "event", "vague", "none"]

class ModelSpan(BaseModel):
    turn_index: int
    label: Label               # the 8-value enum
    owner: str | None
    recipient: str | None
    action: str | None
    due: ModelDue
    condition: str | None
    confidence: float          # Field(ge=0, le=1): stripped from the API schema, checked by the SDK
    quote: str
    rationale: str             # described as "a one-sentence explanation", never "reasoning"
    ambiguous: bool

class ModelOutput(BaseModel):  # structured outputs need an object at the root
    spans: list[ModelSpan]
```

The schema sits inside the documented limits: 5 nullable fields (each is an `anyOf` with null, limit 16 union
parameters per request) and no optional parameters (limit 24); every field is required and nullable instead.

## Why one call per transcript

| | One call per transcript (chosen) | One call per turn |
| --- | --- | --- |
| Requests for a 60 s clip (10–20 turns) | 1 | 10–20 |
| Latency against the 10 s target | One model round trip | Parallel round trips; the slowest sets the latency, and rate limits apply per request |
| Tokens | System prompt once; transcript once | System prompt per call (cheap once cached); each turn plus its predecessor |
| Multi-span utterances (#6), request-and-reply (#5) | Natural: the model sees both turns | Works, but the reply call must carry the request turn |
| Context control | Prompt rule only; the model *can* see later turns | Exact: the call only contains the turn and its predecessor |
| Failure blast radius | One bad response invalidates the whole transcript (retried once) | One bad turn |
| Cost of a retry | Whole transcript | One turn |

The main risk of the chosen design is **context leakage**: the model sees the whole transcript and may let a
later turn change an earlier label (for example, label a REQUEST as COMMITMENT because the other party
agreed two turns later). Mitigations:

1. The prompt states the rule explicitly and the few-shots include a request whose reply comes later and stays
   REQUEST, with the reply labelled COMMITMENT.
2. Each span carries `turn_index`, so the eval can report accuracy on multi-turn items separately.
3. If the eval shows leakage, a per-turn variant (`prompts/v2`, adapter unchanged) is a contained change: the
   extractor loops over turns and merges, and the eval compares both by prompt version.

Size guardrail: `/analyze` rejects transcripts over 200 turns or 20,000 characters (422). A 60 s clip is
around 150 words, so the cap only stops abuse of text mode.

## Why not forced tool use

The first plan forced a tool call (`tool_choice: {"type": "tool"}`) to get JSON. On Claude Opus 5.5 and
Claude Sonnet 5.5, `any` and `tool` return a 400 error; the documented alternatives are `auto` with strict tool
use, or structured outputs "when you need a response in a fixed JSON shape" (Define tools, "Forcing tool use").
Structured outputs fit exactly: no tool is being called, we want one JSON document back. They also work on
Haiku 5.5, so all three comparison models share one code path.

## Structured outputs: behaviour we rely on

- `client.messages.parse()` sends the schema as `output_config.format`, validates the reply against the
  original Pydantic model and returns it as `parsed_output` (Structured outputs, "Usage").
- Unsupported constraints (`minimum`/`maximum` on `confidence`) are removed from the API schema, written into
  the field description, and still enforced by the SDK's validation ("How SDK transformation works").
- Enum casing may drift ("Commitment" for "COMMITMENT") with no error ("Invalid outputs"), so `Label` parses
  case-insensitively.
- A new schema costs a one-time grammar compilation; compiled grammars are cached for 24 hours from last use,
  and changing descriptions does not invalidate them ("Grammar compilation and caching"). The eval's first item
  is slower; latency percentiles exclude nothing but the report notes it.
- Structured outputs add a format system prompt (extra input tokens), and changing the format invalidates the
  prompt cache ("Prompt modification and token costs"). The schema is fixed per prompt version, so it stays
  stable within a run.
- A refusal (`stop_reason: "refusal"`) or truncation (`"max_tokens"`) can return output that does not match
  the schema ("Invalid outputs"). Both are checked before parsing (next section).
- A field that asks for "reasoning" can trigger a `reasoning_extraction` refusal, so `rationale` asks for a
  short explanation ("Invalid outputs"; Define tools, "Best practices").

## Validation, retry and errors

```text
response = parse(...)
├─ stop_reason == "refusal"     → ModelRefused (no retry; category logged, not text)
├─ stop_reason == "max_tokens"  → counts as invalid → retry once
├─ SDK validation error         → invalid → retry once
└─ parsed ModelOutput → our checks:
     - turn_index within the transcript
     - condition present when label == CONDITIONAL
     - owner present for COMMITMENT/HEDGED/CONDITIONAL
   any failure                   → invalid → retry once
retry: append the assistant content unchanged + a user message with the validation errors (field paths and
       messages only, never transcript text); one attempt; a second failure → ModelOutputInvalid
```

The retry appends to the conversation instead of rewriting it. That matters on Opus 5.5 and Sonnet 5.5, whose
thinking blocks are bound to the conversation that produced them; passing `response.content` back unchanged is
the documented append-only pattern.

SDK transport errors (429, 5xx, timeouts) are retried by the SDK itself (`max_retries=2`, default timeout
10 minutes; we set 60 s). They surface as `ExtractionError` after that, and the API maps them to 502.

### Refusal fallback

Current guidance for Opus 5.5 and Sonnet 5.5 is to enable server-side fallbacks (`fallbacks: "default"` with
the `server-side-fallback-2026-07-01` beta), which reruns a refused request on another model inside the same
call. It is on for the API and the eval, and `response.model` goes into the metadata, so the eval can see
when a different model answered. Haiku 5.5 has no server-side fallback; a refusal there is
`ModelRefused`.

## Post-pass (deterministic code)

1. **Quote check.** `quote` must be a substring of `turns[turn_index].text`. Failures are dropped, counted in
   `metadata.dropped_quotes`, and logged as `hallucinated_quote turn=3 length=41` (no quote text).
2. **Dates.** `due.raw` goes through the resolver with `call_date`; the resolver sets `resolved` and
   `precision`. When it can't parse the phrase, `resolved` is null and `precision` falls back to the model's
   hint, restricted to `event` or `vague`.
3. **Ledger flags.** `in_ledger` for COMMITMENT, HEDGED and CONDITIONAL; `soft` for HEDGED.

## Model, effort and cost

| Model | Input $/MTok | Output $/MTok | Cache read | Effort default | Note |
| --- | --- | --- | --- | --- | --- |
| `claude-opus-5-5` | 4.00 | 20.00 | 0.20 | `medium` | Thinking always on; forced `tool_choice` rejected |
| `claude-sonnet-5-5` | 2.00 | 10.00 | 0.10 | `high` | Forced `tool_choice` rejected |
| `claude-haiku-5-5` | 0.10 | 0.50 | 0.01 | `medium` | Prices for prompts up to 100K tokens |

- Effort is set explicitly from settings (`EXTRACTOR_EFFORT`, default `medium`) and written into every eval
  report, because defaults differ by model and an effort sweep is part of the Part 3 comparison.
- `pricing.py` holds this table; cost = uncached input + cache writes (1.25x) + cache reads + output. An
  unknown model id gives `cost_usd: null`.
- **Rough eval cost**, 24 items, about 2,500 cached system tokens, 200 transcript tokens and about 1,000
  output tokens (thinking included) per item: about $0.50 on Opus 5.5, $0.25 on Sonnet 5.5, $0.02 on Haiku 5.5.
  The first real run will replace these estimates with measured numbers.

## Prompt caching

- The system prompt is the stable prefix (render order is tools → system → messages) and gets
  `cache_control: {"type": "ephemeral"}`; it is well above the 512-token minimum for these models.
- Writes cost 1.25x base input; reads cost 0.05x on Opus 5.5 and Sonnet 5.5 and 0.1x on Haiku 5.5. The
  default lifetime is 5 minutes, refreshed on each hit.
- The eval runs one item first to write the cache, then fans out under the concurrency limit, so concurrent
  first requests don't each pay for a write.
- `usage.cache_creation_input_tokens` and `usage.cache_read_input_tokens` go into the metadata; a run where
  reads stay at zero is flagged in the report.

## Tests (all offline)

- `FakeAdapter` returns scripted `ModelOutput`s or raises scripted errors. It covers a valid reply, the retry
  after an invalid reply, two invalid replies leading to `ModelOutputInvalid`, a refusal, a truncation, and a
  dropped quote.
- `test_anthropic_adapter.py` checks the request the adapter builds (model, effort, cache marker, schema,
  `max_tokens`) with a stubbed client, and how it maps usage and stop reasons. It makes no network calls.
- The prompt test asserts that v1 contains every label definition and the context rule, and that the
  few-shot examples parse as `ModelOutput`.

## Decisions (accepted 2026-10-21)

1. Default model `claude-opus-5-5`; Sonnet 5.5 and Haiku 5.5 are comparison runs (`--model`).
2. Server-side refusal fallback is on for the API and the eval; the metadata records which model answered.
3. Effort is `medium` for every model, set explicitly so runs compare like for like.
4. `/analyze` rejects transcripts over 200 turns or 20,000 characters.

## Sources

| Claim | Page and section |
| --- | --- |
| Forced `tool_choice` returns 400 on Opus 5.5 and Sonnet 5.5; use structured outputs for fixed JSON | [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools), "Forcing tool use" |
| Tool-use system prompt tokens; no `any`/`tool` column for Opus 5.5 and Sonnet 5.5 | [Tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview), "Pricing" |
| `output_config.format`, `messages.parse()`, supported models | [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), "How it works", "Usage" |
| Schema limits (unsupported keywords, 24 optional, 16 union parameters) | Structured outputs, "JSON Schema limitations", "Explicit limits" |
| SDK strips and re-validates unsupported constraints | Structured outputs, "How SDK transformation works" |
| Grammar compilation and 24-hour cache | Structured outputs, "Grammar compilation and caching" |
| Refusal, `max_tokens` and enum casing behaviour | Structured outputs, "Invalid outputs" |
| Extra format system prompt; changing format invalidates the cache | Structured outputs, "Prompt modification and token costs" |
| Effort levels and per-model defaults | [Effort](https://platform.claude.com/docs/en/build-with-claude/effort), "How effort works", per-model sections |
| Cache minimum 512 tokens, multipliers, TTL, render order, usage fields | [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), "How prompt caching works", "Pricing", "Tracking cache performance" |
| Model prices, cache-hit prices, Batch API at 50% | [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), "Model pricing", "Batch processing" |
| Ask for an explanation, not reasoning | Define tools, "Best practices for tool definitions" |
| Async client, timeouts, retries | [Python SDK](https://github.com/anthropics/anthropic-sdk-python) README; the async form of `messages.parse()` gets confirmed against the installed SDK in commit 6 |
