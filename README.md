# Commitment Tracker AI

Commitment Tracker AI reads a conversation transcript and returns the commitments in it: who promised what, to
whom, and by when. Every statement gets one of eight labels, so a firm promise is kept apart from a hedge, a
request, a promise someone else made, or a refusal.

```http
POST /analyze
{
  "call_date": "2026-10-21",
  "transcript": [
    {"speaker": "buyer",  "text": "Could you send the updated SOW before Thursday?"},
    {"speaker": "seller", "text": "Yes, I will get it to you tomorrow morning."}
  ]
}
```

```json
{
  "spans": [
    {"turn_index": 0, "label": "REQUEST", "owner": null, "action": "send the updated SOW",
     "due": {"raw": "before Thursday", "resolved": "2026-10-21", "precision": "day"}, "in_ledger": false},
    {"turn_index": 1, "label": "COMMITMENT", "owner": "seller", "recipient": "buyer",
     "action": "send the updated SOW", "quote": "Yes, I will get it to you tomorrow morning.",
     "due": {"raw": "tomorrow morning", "resolved": "2026-10-22", "precision": "day"},
     "confidence": 0.93, "in_ledger": true, "soft": false}
  ],
  "metadata": {"model": "claude-haiku-5-5", "attempts": 1, "dropped_quotes": 0, "latency_ms": 5778,
               "cost_usd": 0.0009}
}
```

The response is abridged; every span also carries `recipient`, `condition`, `quote`, `rationale` and
`ambiguous`, and the metadata carries token counts and the model that answered.

This is Part 1 of the project: text in, validated labels out, plus an evaluation harness. Audio, the web demo and
deployment come later ([spec](docs/spec.md)).

## How it works

The model proposes and code decides. One request per transcript goes to Claude with the output schema enforced
as structured output. The reply is then validated, and anything that fails validation gets one retry with the
errors attached. Every quote must appear word for word in its turn, and spans with a quote that doesn't are
dropped and counted. Due dates are resolved by tested code from the call date, never by the model: "end of next
week" on Wednesday 21 October is Friday 30 October. The design and its sources are in
[docs/plans/part-1-extraction-call.md](docs/plans/part-1-extraction-call.md).

The API never logs transcript text, and error responses never echo it back.

## Labels

COMMITMENT, HEDGED and CONDITIONAL create a ledger entry; the other five are near misses.

| Label | Meaning | Example | Ledger |
| --- | --- | --- | --- |
| COMMITMENT | The speaker binds themselves or their team to a specific action | "I'll send the pricing by Friday." | Yes |
| HEDGED | An action is named but the obligation is softened | "I'll try to get that over this week." | Yes, marked soft |
| CONDITIONAL | A commitment that depends on a stated condition | "If legal signs off, we'll ship Monday." | Yes, with the condition |
| SUGGESTION | An idea with no owner bound to it | "We should probably revisit pricing." | No |
| REQUEST | Asks the other party to act | "Can you send the deck?" | No |
| REPORTED | Someone else's promise, retold | "Sarah said she'd send it." | No |
| REFUSAL | Declines or withholds a commitment | "I can't promise the 15th." | No |
| NONE | Facts, past events, policy, small talk | "Our SLA is four hours." | No |

A reply such as "Sure, I'll do it" is a COMMITMENT when the preceding turn asked for something, so each turn is
judged with the turn before it.

## Setup

You need Python 3.12 or later, [uv](https://docs.astral.sh/uv/), and Anthropic credentials. Either sign in with
the Anthropic CLI (`ant auth login`), or set `ANTHROPIC_API_KEY` in the environment or in `backend/.env`, which is
git-ignored.

```bash
cd backend
uv sync
```

## Run the API

```bash
cd backend
uv run uvicorn commitment_tracker.api.app:app --port 8000
```

```bash
curl -X POST http://localhost:8000/analyze -H "content-type: application/json" -d '{"call_date": "2026-10-21", "transcript": [{"speaker": "seller", "text": "I will send the pricing by Friday."}]}'
```

`GET /health` reports the model and prompt version. A request is limited to 200 turns and 20,000 characters.
Errors share one body, `{"error": {"code", "message", "details"}}`:

| Status | Code | When |
| --- | --- | --- |
| 422 | `validation_error` | The request is malformed or too large; `details` names the fields |
| 422 | `model_refused` | The model declined the transcript |
| 502 | `model_unavailable` | The model API failed after retries, or no credentials are set |
| 502 | `model_output_invalid` | The model's output failed validation twice |

The OpenAPI schema is committed as [openapi.json](openapi.json); regenerate it with `uv run export-openapi` after
changing a model or route. A test fails when it is out of date.

Settings come from the environment or `backend/.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `EXTRACTOR_MODEL` | `claude-opus-5-5` | Model id |
| `EXTRACTOR_EFFORT` | `medium` | `low`, `medium`, `high`, `xhigh` or `max` |
| `EXTRACTOR_MAX_TOKENS` | `16000` | Output limit per call, thinking included |
| `PROMPT_VERSION` | `v1` | File in `backend/src/commitment_tracker/extractor/prompts/` |
| `MODEL_TIMEOUT_SECONDS` | `60` | Per request; the SDK retries twice on rate limits and server errors |
| `ANTHROPIC_API_KEY` | unset | Optional when signed in with `ant auth login` |

## Evaluate

```bash
cd backend
uv run eval --model claude-haiku-5-5 --prompt v1
```

The runner sends each item in [backend/eval/data/dev.jsonl](backend/eval/data/dev.jsonl) through the extractor,
four at a time (`--concurrency`), and writes a JSON report and a markdown summary to `backend/eval/reports/`. The
report covers:

- precision and recall per label, and a confusion matrix
- ledger F1: the three ledger labels against everything else
- accuracy of owner, action and resolved due date on ledger spans
- quote-check failures, retries, p50 and p95 latency, and total cost

Items tagged `ambiguous`, such as sarcasm, are listed separately and left out of the headline numbers. The command
exits 1 if any item failed, after writing the report.

Each call costs money. Responses are cached in `backend/eval/.cache/` by transcript, model, prompt text and effort,
so a rerun only calls the model for what changed. The cache stores finished responses, including resolved dates:
after changing the extractor or the date resolver, run with `--no-cache` or delete the cache folder.

### Results

| Model | Prompt | Dataset | Ledger F1 | Label accuracy | Field accuracy (owner / action / due) | p50 / p95 latency | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude-haiku-5-5, medium effort | v1 | 24 seed items | 1.000 | 1.000 | 13/13, 11/11, 13/13 | 1.5 s / 2.6 s | $0.0046 |

The 24 seed items are the development set. The prompt was written with them in view, so this row confirms the
pipeline end to end rather than measuring accuracy. Accuracy will be measured on a held-out set of 150 items,
which comes later with the comparison across models.

## Develop

Run these from `backend/`. Tests make no network calls.

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

The code lives in `backend/src/commitment_tracker/`:

- `schemas.py`: the request and response models
- `extractor/`: the prompt files, the Anthropic adapter, validation and retry, and the date resolver
- `api/`: the FastAPI app
- `evaluation/`: the dataset loader, matching, metrics, cache and reports

A test enforces the import rules between them. Conventions for contributors and coding agents are in
[CLAUDE.md](CLAUDE.md).

Versions and the changelog come from release-please, driven by Conventional Commit types; never bump a version by
hand. See [docs/releasing.md](docs/releasing.md).

## License

MIT; see [LICENSE](LICENSE).
