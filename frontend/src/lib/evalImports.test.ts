import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { components } from "@/api/schema";
import { extendedTest, failure, fakeClient, ok } from "@/lib/testExports";
import { type CheckResult, checkImport, importBatch, optionProblems, readRequest } from "./evalImports";

type ImportResult = components["schemas"]["ImportRequest"];
type ImportReport = components["schemas"]["ImportReport"];
type ImportRequest = components["schemas"]["ImportRequest"];
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

const importRequest = (over: Partial<ImportRequest> = {}): ImportRequest => {
  return {
    batch: "gem02",
    source: "gem02.jsonl",
    content: "{}\n",
    provenance: "gemini-3-pro",
    today: "2026-06-06",
    generation_prompt: null,
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

describe("request file", () => {
  extendedTest("request file", async ({ tmpDir }) => {
    const sourceFile = join(tmpDir, "gem02.jsonl");
    const request: ImportRequest = importRequest({
      source: sourceFile,
      today: new Date().toISOString().slice(0, 10),
    });
    const file: File = new File([request.content], request.source);
    const options = { batch: request.batch, provenance: request.provenance };
    const response = await readRequest(file, options);
    expect(response).toEqual({ ok: true, job: request });
  });
});
