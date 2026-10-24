import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import indexJson from "@/data/evals/index.json";
import { compareRuns, filterItems, NO_FILTER, parseIndex, parseRun, share, signed } from "@/lib/evals";
import { row, singleRun, twoStageRun } from "@/test/evalFixtures";

const RUNS = path.resolve(import.meta.dirname, "../data/evals/runs");

describe("the committed export", () => {
  it("matches the types the pages use", () => {
    const index = parseIndex(indexJson);
    const files = readdirSync(RUNS).filter((name) => name.endsWith(".json"));
    expect(files.map((name) => name.replace(/\.json$/, "")).sort()).toEqual(index.runs.map((r) => r.run).sort());
    for (const name of files) {
      const run = parseRun(JSON.parse(readFileSync(path.join(RUNS, name), "utf8")));
      expect(run.items.length).toBe(run.scores.items);
    }
  });

  it("is refused when a field the pages need is missing", () => {
    expect(() => parseIndex({ sets: [], runs: [] })).toThrow(/missing results/);
    const { items: _items, ...noItems } = singleRun;
    expect(() => parseRun(noItems)).toThrow(/missing items/);
  });
});

describe("filtering items", () => {
  it("keeps everything by default", () => {
    expect(filterItems(singleRun.items, NO_FILTER)).toHaveLength(3);
  });

  it.each([
    [{ verdict: "wrong" as const }, ["gem01-02"]],
    [{ verdict: "right" as const }, ["gem01-01", "hand01-01"]],
    [{ tag: "multi_turn" }, ["hand01-01"]],
    [{ provenance: "hand-written" }, ["hand01-01"]],
    [{ label: "HEDGED" }, ["gem01-02"]],
    [{ label: "COMMITMENT", verdict: "wrong" as const }, ["gem01-02"]],
  ])("by %o", (filter, ids) => {
    expect(filterItems(singleRun.items, { ...NO_FILTER, ...filter }).map((i) => i.id)).toEqual(ids);
  });
});

describe("comparing runs", () => {
  const verdicts = (run: typeof singleRun) => Object.fromEntries(run.items.map((i) => [i.id, i.correct]));

  it("finds items that flipped each way", () => {
    const comparison = compareRuns(
      { row: row(singleRun.id, "haiku"), correct: verdicts(singleRun) },
      { row: row(twoStageRun.id, "two-stage", { ledger_f1: 0.5 }), correct: verdicts(twoStageRun) },
    );
    expect(comparison.regressions).toEqual(["gem01-01"]);
    expect(comparison.fixes).toEqual(["gem01-02"]);
    expect([comparison.bothRight, comparison.bothWrong]).toEqual([1, 0]);
    expect(comparison.deltas[0]).toEqual({ metric: "Ledger F1", a: 0.667, b: 0.5 });
  });
});

describe("formatting", () => {
  it("signs changes with a real minus", () => {
    expect([signed(0.25), signed(-0.1), signed(0), signed(null)]).toEqual(["+0.250", "−0.100", "±0.000", "n/a"]);
  });

  it("shares a count of its row, and an empty row as zero", () => {
    expect([share(1, [1, 3]), share(0, [0, 0])]).toEqual([0.25, 0]);
  });
});
