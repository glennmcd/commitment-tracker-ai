import type { ApiClient } from "@/api/client";
import type { EvalRun } from "@/lib/evals";
import type { TurnInput } from "./transcript";
import { codeOf, explain, NETWORK, type JobResult } from "./jobs";

export interface EvalRunStatus {
  run_id:      string
  status:      "queued" | "running" | "done" | "failed"
  items_done:  number
  items_total: number
  cost_usd:    number | null      // spent so far
  error_code:  string | null
  report:      EvalRun | null     // when done: the same shape as src/data/evals/runs/*.json
}

export async function startEvalRun(client: ApiClient, choice: { set: string; configuration: string; offline: boolean }): Promise<JobResult> {
  try {
    const { data, error, response } = await client.POST("/eval-runs", { body: choice });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}