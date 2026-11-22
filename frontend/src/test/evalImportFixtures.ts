/** Import reports in the API's shape: a clean one, one with every kind of finding, and one with nothing valid. */
import type { components } from "@/api/schema";

type ImportReport = components["schemas"]["ImportReport"];

export function report(over: Partial<ImportReport> = {}): ImportReport {
  return {
    batch: "gpt03",
    source: "chatgpt.jsonl",
    provenance: "chatgpt-luna",
    generation_prompt: "prompt-v1",
    imported_on: "2026-10-29",
    imported: 22,
    rejections: [],
    date_disagreements: [],
    near_duplicates: [],
    ...over,
  };
}

export const withProblems = report({
  rejections: [
    {
      line: 37,
      reason: "expected.1.action_keywords: Value error, action_keywords must be non-empty lower case words",
    },
  ],
  date_disagreements: [{ item: "gpt03-11", span: 0, generator: null, resolver: "2026-11-12" }],
  near_duplicates: [{ item: "gpt03-04", of: "test:gem01-07", ratio: 0.912 }],
});

export const nothingValid = report({
  imported: 0,
  rejections: [{ line: 1, reason: "invalid JSON: Expecting value" }],
});
