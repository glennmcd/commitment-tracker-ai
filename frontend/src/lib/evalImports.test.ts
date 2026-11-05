import { describe, expect, it } from "vitest";
import type { components } from "@/api/schema";
import { failure, fakeClient, ok } from "@/lib/testExports";
import { type CheckResult, checkImport, importBatch, optionProblems } from "./evalImports";

type ImportResult = components["schemas"]["ImportRequest"];
type ImportReport = components["schemas"]["ImportReport"];
describe("optionProblems", () => {
  it.each([
    [{ batch: "", provenance: "gemini-3-pro" }, { batch: "Missing batch" }],
    [{ batch: "gem02", provenance: "" }, { provenance: "Missing provenance" }],
    [{ batch: "gem02", provenance: "gemini-3-pro" }, {}],
    [{ batch: "Gem02", provenance: "gemini-3-pro" }, { batch: "Use lower-case letters, digits and dashes." }],
    [{ batch: "gem02", provenance: "spec" }, { provenance: "spec is reserved for the the spec's seed items." }],
    [{ batch: "gem02", provenance: "Gemini" }, { provenance: "use hand-written or <family>-<model>" }],
    [{ batch: "hw01", provenance: "hand-written" }, {}],
  ])("checks %o", (options, problems) => expect(optionProblems(options)).toEqual(problems));
});

const importResult = (over: Partial<ImportResult> = {}): ImportResult => {
  return {
    batch: "gem02",
    source: "s",
    content: "",
    provenance: "gemini-3-pro",
    today: "2026-06-06",
    generation_prompt: null,
    ...over,
  };
};
const importReport = (over: Partial<ImportReport> = {}): ImportReport => {
  return {
    batch: "gem02",
    source: "",
    provenance: "",
    generation_prompt: null,
    imported_on: "",
    imported: 0,
    rejections: [],
    date_disagreements: [],
    near_duplicates: [],
    ...over,
  };
};

describe("basic checkImport", () => {
  it("should return the correct report", async () => {
    const result: ImportReport = importReport();

    const { client, post } = fakeClient([ok<ImportReport>(result, 200)]);
    const request: ImportResult = importResult();

    const response: CheckResult = await checkImport(client, request);
    expect(post).toHaveBeenCalledWith("/eval-imports/check", { body: request });
    expect(response).toEqual({ ok: true, job: result });
  });
});

describe("basic importBatch", () => {
  it("should return the correct report", async () => {
    const result: ImportReport = importReport();

    const { client, post } = fakeClient([ok<ImportReport>(result, 200)]);
    const request: ImportResult = importResult();

    const response: CheckResult = await importBatch(client, request);
    expect(post).toHaveBeenCalledWith("/eval-imports", { body: request });
    expect(response).toEqual({ ok: true, job: result });
  });
});
