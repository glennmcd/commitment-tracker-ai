import type { ApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { explainFailure, NETWORK } from "./apiErrors";

type ImportResult = components["schemas"]["ImportRequest"];
type ImportReport = components["schemas"]["ImportReport"];
type ImportRequest = components["schemas"]["ImportRequest"];
export type CheckResult = { ok: true; job: components["schemas"]["ImportReport"] } | { ok: false; message: string };

export function optionProblems(options: { [key: string]: any }): { [key: string]: any } {
  const problems: { [key: string]: any } = {};

  if (!("batch" in options) || !options["batch"] || options["batch"].trim() === "") {
    problems["batch"] = "Missing batch";
  }
  if (!("provenance" in options) || !options["provenance"]) {
    problems["provenance"] = "Missing provenance";
  }
  if (options["provenance"] && options["provenance"] === "spec") {
    problems["provenance"] = "spec is reserved for the the spec's seed items.";
  }
  if (options["provenance"] && options["provenance"] !== "spec" && !/^[a-z]+-[a-z0-9-]+$/.test(options["provenance"])) {
    problems["provenance"] = "use hand-written or <family>-<model>";
  }
  if ("batch" in options && options["batch"].trim() !== "" && !/^[a-z0-9-]+$/.test(options["batch"])) {
    problems["batch"] = "Use lower-case letters, digits and dashes.";
  }
  return problems;
}

export function importSummary(options: { [key: string]: any }): string {
  let result: string = `imported: ${options["imported"]}`;
  result += ` | `;
  result += `rejected: ${options["rejected"] != undefined ? (options["rejected"] as any[]).length : 0}`;
  result += ` | `;
  result += `date disagreements: ${options["dateDisagreements"] != undefined ? (options["dateDisagreements"] as any[]).length : 0}`;
  result += ` | `;
  result += `near duplicates: ${options["nearDuplicates"] != undefined ? (options["nearDuplicates"] as any[]).length : 0}`;
  return result;
}
export async function checkImport(client: ApiClient, request: ImportResult): Promise<CheckResult> {
  try {
    const { data, error, response } = await client.POST("/eval-imports/check", { body: request });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explainFailure(error, response) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}

export async function importBatch(client: ApiClient, request: ImportResult): Promise<CheckResult> {
  try {
    const { data, error, response } = await client.POST("/eval-imports", { body: request });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explainFailure(error, response) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}

export async function readRequest(
  file: File,
  options: { [key: string]: any },
): Promise<{ ok: true; job: ImportRequest } | { ok: false; message: string }> {
  try {
    const date = new Date().toISOString().slice(0, 10);
    const content = await file.text();
    const request: ImportRequest = {
      batch: options["batch"],
      source: file.name,
      content,
      provenance: options["provenance"],
      today: date,
      generation_prompt: null,
    };
    return { ok: true, job: request };
  } catch (error) {
    return { ok: false, message: String(error) };
  }
}
