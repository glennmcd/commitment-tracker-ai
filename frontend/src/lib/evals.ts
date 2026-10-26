/**
 * Types and selectors for the evaluation data that `uv run eval-export-site` writes to src/data/evals/
 * (backend/src/commitment_tracker/evaluation/site_export.py). The pages read it at build time; nothing is fetched.
 * The types are kept by hand; `parseIndex` and `parseRun` check the parts the pages rely on, and a test runs them
 * over the committed export so a change on the Python side fails here rather than on the page.
 */
import type { Label } from "@/lib/labels";

export const LABEL_ORDER: Label[] = [
  "COMMITMENT",
  "HEDGED",
  "CONDITIONAL",
  "SUGGESTION",
  "REQUEST",
  "REPORTED",
  "REFUSAL",
  "NONE",
];

export interface SetSummary {
  name: string;
  role: string;
  gated: boolean;
  kind: string | null;
  description: string;
  items: number;
  sha256: string;
  review: Record<string, number>;
  labels: Record<string, number>;
  provenance: Record<string, number>;
  error: string | null;
}

export interface RunRow {
  run: string;
  set: string;
  configuration: string;
  model: string;
  stages: Record<string, string>;
  prompt_version: string;
  prompt_sha256: string;
  effort: string;
  started_at: string;
  legacy: boolean;
  set_sha256: string | null;
  items: number;
  ledger_f1: number;
  ledger_precision: number;
  ledger_recall: number;
  accuracy: number;
  macro_f1: number;
  fields: Record<string, number | null>;
  failed_items: number;
  cost_usd: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  escalation_rate: number | null;
  screen_misses: number | null;
}

export interface AudioSlice {
  clips: number;
  ledger_f1_audio: number;
  ledger_f1_text: number;
  penalty: number;
}

export interface AudioRow {
  run: string;
  configuration: string;
  slices: Record<string, AudioSlice>;
  turn_mismatches: number;
  speaker_errors: number;
  unmatched_spans: number;
}

export interface AgreementRow {
  key: string;
  spans: number;
  agreement: number;
  kappa: number | null;
}

export interface EvalIndex {
  sets: SetSummary[];
  results: Record<string, RunRow[]>;
  runs: RunRow[];
  audio: AudioRow[];
  agreement: { generators: AgreementRow[]; labels: AgreementRow[] };
}

export interface LabelScore {
  precision: number;
  recall: number;
  f1: number;
  support: number;
}

export interface Scores {
  items: number;
  scored_items: number;
  accuracy: number;
  macro_f1: number;
  labels: Record<string, LabelScore>;
  confusion: { labels: string[]; rows: number[][] };
  ledger: {
    precision: number;
    recall: number;
    f1: number;
    true_positives: number;
    false_positives: number;
    false_negatives: number;
  };
  fields: Record<string, { correct: number; total: number; accuracy: number | null }>;
  ambiguous: { item_id: string; expected: string; predicted: string }[];
  failed_items: { item_id: string; error: string }[];
  quote_failures: number;
  retried_items: number;
  cache_hits: number;
  latency_ms: { p50: number; p95: number } | null;
  cost_usd: number | null;
}

export interface ExpectedSpan {
  turn_index: number;
  label: Label;
  quote: string;
  owner: string | null;
  recipient: string | null;
  action_keywords: string[];
  due_raw: string | null;
  due_resolved: string | null;
  precision: string;
  condition: string | null;
}

export interface PredictedSpan {
  turn_index: number;
  label: Label;
  quote: string;
  owner: string | null;
  recipient: string | null;
  action: string | null;
  due_raw: string | null;
  due_resolved: string | null;
  precision: string;
  condition: string | null;
}

export interface RunItem {
  id: string;
  tags: string[];
  provenance: string | null;
  call_date: string | null;
  note: string | null;
  turns: { speaker: string; text: string }[] | null;
  expected: ExpectedSpan[] | null;
  expected_labels: string[];
  predicted: PredictedSpan[] | null;
  predicted_labels: string[];
  correct: boolean | null;
  error: string | null;
  cached: boolean;
  latency_ms: number | null;
  cost_usd: number | null;
  dropped_quotes: number | null;
  flagged_turns: number[] | null;
}

export interface RunInfo {
  model: string;
  prompt_version: string;
  prompt_sha256: string;
  effort: string;
  dataset: string;
  started_at: string;
  duration_seconds: number;
  served_by: string[];
  set_name: string | null;
  set_sha256: string | null;
  set_items: number | null;
  configuration: string | null;
  stages: Record<string, string>;
}

export interface ProvenanceScore {
  items: number;
  scored_items: number;
  ledger_f1: number;
  ledger_precision: number;
  ledger_recall: number;
  accuracy: number;
}

export interface TwoStageScores {
  turns: number;
  flagged_turns: number;
  escalation_rate: number;
  screen_misses: number;
  screen_miss_items: string[];
  stage_cost_usd: Record<string, number | null>;
}

export interface EvalRun {
  id: string;
  set: string;
  configuration: string; // the configuration's name, or the model id for runs without one
  legacy: boolean;
  audio: boolean;
  run: RunInfo;
  scores: Scores;
  by_provenance: Record<string, ProvenanceScore>;
  two_stage: TwoStageScores | null;
  audio_scores: (Omit<AudioRow, "run" | "configuration"> & { text_set_sha256: string }) | null;
  items: RunItem[];
}

// ---- Runtime checks -------------------------------------------------------------------------------------------

function need(value: unknown, keys: string[], where: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null) throw new Error(`${where}: not an object`);
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    if (!(key in record)) throw new Error(`${where}: missing ${key}`);
  }
  return record;
}

const ROW_KEYS = ["run", "set", "configuration", "model", "prompt_version", "started_at", "legacy", "ledger_f1"];

export function parseIndex(data: unknown): EvalIndex {
  const index = need(data, ["sets", "results", "runs", "audio", "agreement"], "index");
  for (const set of index.sets as unknown[]) need(set, ["name", "role", "gated", "items", "labels"], "set");
  for (const row of index.runs as unknown[]) need(row, ROW_KEYS, "run row");
  for (const rows of Object.values(index.results as Record<string, unknown[]>)) {
    for (const row of rows) need(row, ROW_KEYS, "results row");
  }
  return data as EvalIndex;
}

export function parseRun(data: unknown): EvalRun {
  const run = need(data, ["id", "set", "configuration", "legacy", "audio", "run", "scores", "items"], "run");
  need(run.scores, ["ledger", "labels", "confusion", "fields", "failed_items"], `${String(run.id)} scores`);
  for (const item of run.items as unknown[]) {
    need(
      item,
      ["id", "tags", "turns", "expected", "predicted", "correct", "expected_labels"],
      `${String(run.id)} item`,
    );
  }
  return data as EvalRun;
}

// ---- Formatting -----------------------------------------------------------------------------------------------

/** The best `count` configurations on a set by ledger F1, label accuracy breaking ties. */
export function topResults(index: EvalIndex, set = "test", count = 3): RunRow[] {
  return [...(index.results[set] ?? [])]
    .sort((a, b) => b.ledger_f1 - a.ledger_f1 || b.accuracy - a.accuracy)
    .slice(0, count);
}

export function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : value.toFixed(3);
}

export function dollars(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : `$${value.toFixed(4)}`;
}

export function seconds(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? "n/a" : `${(ms / 1000).toFixed(1)} s`;
}

export function signed(value: number | null): string {
  if (value === null) return "n/a";
  return `${value > 0 ? "+" : value < 0 ? "−" : "±"}${Math.abs(value).toFixed(3)}`;
}

export function shortDate(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

// ---- Selectors ------------------------------------------------------------------------------------------------

export type Verdict = "all" | "right" | "wrong";

export interface ItemFilter {
  label: string; // "" for any; otherwise an expected or predicted label
  tag: string;
  provenance: string;
  verdict: Verdict;
}

export const NO_FILTER: ItemFilter = { label: "", tag: "", provenance: "", verdict: "all" };

export function filterItems(items: RunItem[], filter: ItemFilter): RunItem[] {
  return items.filter((item) => {
    if (filter.label && ![...item.expected_labels, ...item.predicted_labels].includes(filter.label)) return false;
    if (filter.tag && !item.tags.includes(filter.tag)) return false;
    if (filter.provenance && item.provenance !== filter.provenance) return false;
    if (filter.verdict === "right" && item.correct !== true) return false;
    if (filter.verdict === "wrong" && item.correct !== false) return false;
    return true;
  });
}

export function distinct(values: (string | null)[]): string[] {
  return [...new Set(values.filter((v): v is string => Boolean(v)))].sort();
}

/** A run reduced to what the compare page needs: its row and each item's verdict. */
export interface RunVerdicts {
  row: RunRow;
  correct: Record<string, boolean | null>;
}

export interface Comparison {
  deltas: { metric: string; a: number | null; b: number | null }[];
  regressions: string[]; // right in a, wrong in b
  fixes: string[]; // wrong in a, right in b
  bothRight: number;
  bothWrong: number;
}

export function sameSet(a: RunRow, b: RunRow): boolean {
  return a.set === b.set && a.set_sha256 !== null && a.set_sha256 === b.set_sha256;
}

export function compareRuns(a: RunVerdicts, b: RunVerdicts): Comparison {
  const metric = (name: string, pick: (row: RunRow) => number | null) => ({
    metric: name,
    a: pick(a.row),
    b: pick(b.row),
  });
  const deltas = [
    metric("Ledger F1", (r) => r.ledger_f1),
    metric("Ledger precision", (r) => r.ledger_precision),
    metric("Ledger recall", (r) => r.ledger_recall),
    metric("Label accuracy", (r) => r.accuracy),
    metric("Macro F1", (r) => r.macro_f1),
    ...Object.keys(a.row.fields).map((field) => metric(`${field} accuracy`, (r) => r.fields[field] ?? null)),
  ];
  const shared = Object.keys(a.correct).filter((id) => id in b.correct);
  const regressions = shared.filter((id) => a.correct[id] === true && b.correct[id] === false);
  const fixes = shared.filter((id) => a.correct[id] === false && b.correct[id] === true);
  return {
    deltas,
    regressions,
    fixes,
    bothRight: shared.filter((id) => a.correct[id] === true && b.correct[id] === true).length,
    bothWrong: shared.filter((id) => a.correct[id] === false && b.correct[id] === false).length,
  };
}

/** Matrix shading: a share of the row's total, for a background tint next to the number (never instead of it). */
export function share(count: number, row: number[]): number {
  const total = row.reduce((sum, n) => sum + n, 0);
  return total ? count / total : 0;
}

// ---- Pairing, as the scorer does it (backend/src/commitment_tracker/evaluation/matching.py) ----------------------

const WORD = /[a-z0-9']+/g;
export const MIN_OVERLAP = 0.6;

/** The share of the shorter quote's words found in the other. */
export function overlap(a: string, b: string): number {
  const wa = new Set(a.toLowerCase().match(WORD) ?? []);
  const wb = new Set(b.toLowerCase().match(WORD) ?? []);
  if (!wa.size || !wb.size) return 0;
  let shared = 0;
  for (const word of wa) if (wb.has(word)) shared += 1;
  return shared / Math.min(wa.size, wb.size);
}

/**
 * Expected span index -> predicted span index. Spans pair only within a turn, one to one, best overlap first (ties by
 * expected then predicted index), and only at MIN_OVERLAP or more: the same greedy rule the scorer uses.
 */
export function pairSpans(expected: ExpectedSpan[], predicted: PredictedSpan[]): Map<number, number> {
  const candidates: [number, number, number][] = [];
  expected.forEach((e, ei) => {
    predicted.forEach((p, pi) => {
      if (e.turn_index === p.turn_index) candidates.push([overlap(e.quote, p.quote), ei, pi]);
    });
  });
  candidates.sort((x, y) => y[0] - x[0] || x[1] - y[1] || x[2] - y[2]);
  const partner = new Map<number, number>();
  const taken = new Set<number>();
  for (const [score, ei, pi] of candidates) {
    if (score < MIN_OVERLAP) break;
    if (!partner.has(ei) && !taken.has(pi)) {
      partner.set(ei, pi);
      taken.add(pi);
    }
  }
  return partner;
}
