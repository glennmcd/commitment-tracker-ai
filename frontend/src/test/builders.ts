import type { Job } from "@/lib/jobs";
import type { Metadata, Span } from "@/lib/labels";

/** Test builders for API responses. */
export function span(over: Partial<Span> = {}): Span {
  return {
    turn_index: 0,
    label: "COMMITMENT",
    owner: "Ana",
    recipient: "Ben",
    action: "send the countersigned copy",
    due: { raw: "by Friday", resolved: "2026-10-23", precision: "day" },
    condition: null,
    confidence: 0.93,
    quote: "I'll send it by Friday",
    rationale: "First-person promise with a date.",
    ambiguous: false,
    in_ledger: true,
    soft: false,
    ...over,
  };
}

export function metadata(over: Partial<Metadata> = {}): Metadata {
  return {
    model: "claude-haiku-5-5",
    served_by: "claude-haiku-5-5",
    prompt_version: "v1",
    latency_ms: 1500,
    input_tokens: 1234,
    output_tokens: 56,
    cache_creation_input_tokens: 0,
    cache_read_input_tokens: 0,
    cost_usd: 0.0021,
    attempts: 1,
    dropped_quotes: 0,
    ...over,
  };
}

export function job(spans: Span[], over: Partial<Job> = {}): Job {
  return {
    job_id: "a".repeat(64),
    status: "done",
    transcript: [
      { speaker: "Ben", text: "Can you send the copy?" },
      { speaker: "Ana", text: "Yes. I'll send it by Friday, thanks." },
    ],
    analysis: { spans, metadata: {} as never },
    error_code: null,
    latency_ms: { upload_ms: null, transcribe_ms: null, analyze_ms: 1500, total_ms: 1800 },
    ...over,
  };
}
