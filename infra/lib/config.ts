import type { Node } from "constructs";

/** Everything lives in the project's one AWS Region (docs/decisions/0007-separate-aws-account.md). */
export const REGION = "us-east-2";

/** The SecureString holding the Anthropic key; the backend reads it at cold start (lambda_handlers.py). */
export const API_KEY_PARAMETER = "/commitment-tracker/prod/ANTHROPIC_API_KEY";

/** The Python handlers in the one zip: `<module>.<function>` under the bundled package. */
export const API_HANDLER = "commitment_tracker.lambda_handlers.api_handler";
export const WORKER_HANDLER = "commitment_tracker.lambda_handlers.worker_handler";

/** The custom metric the backend writes (guardrails/metrics.py): the day's spending as a fraction of the cap. */
export const METRIC_NAMESPACE = "CommitmentTracker";
export const SPEND_FRACTION_METRIC = "DailySpendFraction";

export const DEFAULT_DAILY_BUDGET_USD = 5;
export const DEFAULT_MONTHLY_BUDGET_USD = 30;

/**
 * A positive number from CDK context (`-c name=5`), or undefined when it is not set. Anything else is an error, so a
 * typo can't silently fall back to a default on a spending limit.
 */
export function positiveNumberContext(node: Node, name: string): number | undefined {
  const raw: unknown = node.tryGetContext(name);
  if (raw === undefined) return undefined;
  const value = typeof raw === "number" ? raw : typeof raw === "string" && raw.trim() !== "" ? Number(raw) : Number.NaN;
  if (!Number.isFinite(value) || value <= 0) throw new Error(`context ${name} must be a positive number`);
  return value;
}
