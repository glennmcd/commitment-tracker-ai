import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import indexJson from "@/data/evals/index.json";
import { loadIndex, loadRun, runIds } from "./evalsData";

vi.mock("node:fs", async (original) => {
  const actual = await original<typeof import("node:fs")>();
  const readFileSync = vi.fn(actual.readFileSync);
  return { ...actual, readFileSync };
});

const BAD_IDS = ["../index", "a/b", "", "runs/../../index", "a b"];
const FIRST_ROW = indexJson.runs[0];
if (!FIRST_ROW) throw new Error("the exported index lists no runs");

beforeEach(() => {
  vi.mocked(readFileSync).mockClear();
});

describe("loadIndex", () => {
  it("parses the exported index", () => {
    const index = loadIndex();
    expect(index.runs.length).toBeGreaterThan(0);
    expect(index.sets.length).toBeGreaterThan(0);
  });
});

describe("runIds", () => {
  it("lists every run in the index, in order", () => {
    expect(runIds()).toEqual(indexJson.runs.map((row) => row.run));
  });
});

describe("loadRun", () => {
  it("loads a run that is in the index", () => {
    const run = loadRun(FIRST_ROW.run);
    expect(run.id).toBe(FIRST_ROW.run);
    expect(run.items.length).toBeGreaterThan(0);
  });

  it("refuses a well-formed id that is not in the index without reading a file", () => {
    expect(() => loadRun("20990101T000000Z-not-a-run-v1")).toThrow("unknown evaluation run");
    expect(readFileSync).not.toHaveBeenCalled();
  });

  it.each(BAD_IDS)("refuses the malformed id %j without reading a file", (id) => {
    expect(() => loadRun(id)).toThrow("unknown evaluation run");
    expect(readFileSync).not.toHaveBeenCalled();
  });

  describe("when the index itself lists a malformed id", () => {
    const runs = indexJson.runs;

    beforeEach(() => {
      // The id pattern must hold even if a bad row reaches the index: it is the guard on the file path.
      indexJson.runs = [...runs, ...BAD_IDS.map((run) => ({ ...FIRST_ROW, run }))];
    });
    afterEach(() => {
      indexJson.runs = runs;
    });

    it.each(BAD_IDS)("still refuses %j without reading a file", (id) => {
      expect(runIds()).toContain(id);
      expect(() => loadRun(id)).toThrow("unknown evaluation run");
      expect(readFileSync).not.toHaveBeenCalled();
    });
  });
});
