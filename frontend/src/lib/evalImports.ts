import type { ApiClient } from "@/api/client";
import type { components } from "@/api/schema";

type ImportResult = components["schemas"]["ImportRequest"];
type ImportReport = components["schemas"]["ImportReport"];
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
  result += `rejected: ${options["rejected"]}`;
  result += ` | `;
  result += `date disagreements ${options["dateDisagreements"]}`;
  result += ` | `;
  result += `near duplicates ${options["nearDuplicates"]}`;
  return result;
}
export const NETWORK = "Could not reach the API. Check your connection and try again.";

export function codeOf(error: unknown): string | undefined {
  return (error as { error?: { code?: string } } | undefined)?.error?.code;
}

export function explain(code: string | null | undefined, retryAfter: string | null): string {
  switch (code) {
    case "rate_limited":
      return `Rate limited. Retry after ${retryAfter ?? "unknown"} seconds.`;
    default:
      return "An unknown error occurred.";
  }
}

export async function checkImport(client: ApiClient, request: ImportResult): Promise<CheckResult> {
  try {
    const { data, error, response } = await client.POST("/eval-imports/check", { body: request });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}

export async function importBatch(client: ApiClient, request: ImportResult): Promise<CheckResult> {
  try {
    const { data, error, response } = await client.POST("/eval-imports", { body: request });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}
