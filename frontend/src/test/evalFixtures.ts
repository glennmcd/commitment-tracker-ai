/** Two small evaluation runs in the export's shape: one single-model, one two-stage, on the same set. */
import type { EvalIndex, EvalRun, RunItem, RunRow, Scores } from "@/lib/evals";
import { LABEL_ORDER } from "@/lib/evals";

const zeroLabels = Object.fromEntries(
  LABEL_ORDER.map((label) => [label, { precision: 0, recall: 0, f1: 0, support: 0 }]),
);

function scores(overrides: Partial<Scores> = {}): Scores {
  const rows = LABEL_ORDER.map(() => LABEL_ORDER.map(() => 0));
  return {
    items: 3,
    scored_items: 3,
    accuracy: 0.667,
    macro_f1: 0.5,
    labels: { ...zeroLabels, COMMITMENT: { precision: 1, recall: 0.5, f1: 0.667, support: 2 } },
    confusion: { labels: [...LABEL_ORDER], rows },
    ledger: { precision: 1, recall: 0.5, f1: 0.667, true_positives: 1, false_positives: 0, false_negatives: 1 },
    fields: { owner: { correct: 1, total: 1, accuracy: 1 }, action: { correct: 0, total: 1, accuracy: 0 } },
    ambiguous: [],
    failed_items: [],
    quote_failures: 0,
    retried_items: 0,
    cache_hits: 0,
    latency_ms: { p50: 1200, p95: 2400 },
    cost_usd: 0.0123,
    ...overrides,
  };
}

export function item(id: string, overrides: Partial<RunItem> = {}): RunItem {
  return {
    id,
    tags: [],
    provenance: "gemini-3-pro",
    call_date: "2026-10-21",
    note: null,
    turns: [
      { speaker: "buyer", text: "Can you send the deck?" },
      { speaker: "seller", text: "Sure, I'll send it Friday." },
    ],
    expected: [
      {
        turn_index: 1,
        label: "COMMITMENT",
        quote: "Sure, I'll send it Friday.",
        owner: "seller",
        recipient: "buyer",
        action_keywords: ["send"],
        due_raw: "Friday",
        due_resolved: "2026-10-23",
        precision: "day",
        condition: null,
      },
    ],
    expected_labels: ["COMMITMENT"],
    predicted: [
      {
        turn_index: 1,
        label: "COMMITMENT",
        quote: "Sure, I'll send it Friday.",
        owner: "seller",
        recipient: "buyer",
        action: "send the deck",
        due_raw: "Friday",
        due_resolved: "2026-10-23",
        precision: "day",
        condition: null,
      },
    ],
    predicted_labels: ["COMMITMENT"],
    correct: true,
    error: null,
    cached: false,
    latency_ms: 1200,
    cost_usd: 0.004,
    dropped_quotes: 0,
    flagged_turns: null,
    ...overrides,
  };
}

const wrong = (id: string, overrides: Partial<RunItem> = {}) =>
  item(id, {
    predicted_labels: ["HEDGED"],
    predicted: [{ ...(item(id).predicted?.[0] as NonNullable<RunItem["predicted"]>[number]), label: "HEDGED" }],
    correct: false,
    ...overrides,
  });

export function row(run: string, configuration: string, overrides: Partial<RunRow> = {}): RunRow {
  return {
    run,
    set: "test",
    configuration,
    model: configuration === "two-stage" ? "two-stage" : `claude-${configuration}-5-5`,
    stages: {},
    prompt_version: "v1",
    prompt_sha256: "b".repeat(64),
    effort: "medium",
    started_at: "2026-10-26T10:00:00+00:00",
    legacy: false,
    set_sha256: "f".repeat(64),
    items: 3,
    ledger_f1: 0.667,
    ledger_precision: 1,
    ledger_recall: 0.5,
    accuracy: 0.667,
    macro_f1: 0.5,
    fields: { owner: 1, action: 0 },
    failed_items: 0,
    cost_usd: 0.0123,
    latency_p50_ms: 1200,
    latency_p95_ms: 2400,
    escalation_rate: null,
    screen_misses: null,
    ...overrides,
  };
}

function run(id: string, configuration: string, items: RunItem[], extra: Partial<EvalRun> = {}): EvalRun {
  return {
    id,
    set: "test",
    configuration,
    legacy: false,
    audio: false,
    run: {
      model: configuration,
      prompt_version: "v1",
      prompt_sha256: "b".repeat(64),
      effort: "medium",
      dataset: "test",
      started_at: "2026-10-26T10:00:00+00:00",
      duration_seconds: 12,
      served_by: [configuration],
      set_name: "test",
      set_sha256: "f".repeat(64),
      set_items: items.length,
      configuration,
      stages: {},
    },
    scores: scores(),
    by_provenance: {},
    two_stage: null,
    audio_scores: null,
    items,
    ...extra,
  };
}

export const singleRun = run("20261026T100000Z-claude-haiku-5-5-v1", "haiku", [
  item("gem01-01"),
  wrong("gem01-02", { tags: ["keyword_trap"] }),
  item("hand01-01", { provenance: "hand-written", tags: ["multi_turn"] }),
]);

export const twoStageRun = run(
  "20261026T110000Z-two-stage-v1",
  "two-stage",
  [
    wrong("gem01-01", { flagged_turns: [1] }),
    item("gem01-02", { flagged_turns: [1] }),
    item("hand01-01", { provenance: "hand-written", tags: ["multi_turn"], flagged_turns: [] }),
  ],
  {
    two_stage: {
      turns: 6,
      flagged_turns: 2,
      escalation_rate: 0.333,
      screen_misses: 1,
      screen_miss_items: ["hand01-01"],
      stage_cost_usd: { screen: 0.0006, extract: 0.02 },
    },
  },
);

export const index: EvalIndex = {
  sets: [
    {
      name: "test",
      role: "test",
      gated: true,
      kind: "text",
      description: "Held-out headline set.",
      items: 3,
      sha256: "f".repeat(64),
      review: { accepted: 2, edited: 1 },
      labels: { COMMITMENT: 3 },
      provenance: { "gemini-3-pro": 2, "hand-written": 1 },
      error: null,
    },
  ],
  results: { test: [row(singleRun.id, "haiku"), row(twoStageRun.id, "two-stage", { ledger_f1: 0.5 })] },
  runs: [row(twoStageRun.id, "two-stage", { ledger_f1: 0.5 }), row(singleRun.id, "haiku")],
  audio: [],
  agreement: { generators: [], labels: [] },
};
