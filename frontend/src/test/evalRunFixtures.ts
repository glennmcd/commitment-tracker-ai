import type { EvalRunStatus } from "@/lib/evalRuns";
import { singleRun } from "@/test/evalFixtures";

export const RUN_ID = "20261028T200000Z-haiku";

export function runStatus(over: Partial<EvalRunStatus>): EvalRunStatus {
  return {
    run_id: RUN_ID,
    status: "running",
    items_done: 0,
    items_total: 68,
    cost_usd: null,
    error_code: null,
    report: singleRun,
    ...over, // spread operator overrides default values with provided ones
  };
}

export const doneRun = runStatus({
  status: "done",
  items_done: 68,
  cost_usd: 0.41,
  report: singleRun,
});
