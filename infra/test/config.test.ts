import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { App } from "aws-cdk-lib";
import { API_HANDLER, API_KEY_PARAMETER, positiveNumberContext, WORKER_HANDLER } from "../lib/config.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const handlers = readFileSync(path.join(here, "../../backend/src/commitment_tracker/lambda_handlers.py"), "utf8");

function appWith(context: Record<string, unknown>): App {
  return new App({ context, analyticsReporting: false });
}

describe("positiveNumberContext", () => {
  it("is undefined when the context is not set", () => {
    expect(positiveNumberContext(appWith({}).node, "dailyBudgetUsd")).toBeUndefined();
  });

  it("reads numbers and the strings the CLI passes for -c name=value", () => {
    expect(positiveNumberContext(appWith({ dailyBudgetUsd: 5 }).node, "dailyBudgetUsd")).toBe(5);
    expect(positiveNumberContext(appWith({ dailyBudgetUsd: "2.5" }).node, "dailyBudgetUsd")).toBe(2.5);
  });

  it.each([0, -1, "0", "abc", "", " ", "NaN", "Infinity", true, null, {}])("rejects %p", (value) => {
    expect(() => positiveNumberContext(appWith({ dailyBudgetUsd: value }).node, "dailyBudgetUsd")).toThrow(
      "context dailyBudgetUsd must be a positive number",
    );
  });
});

describe("the contract with the backend", () => {
  it("names handlers that exist in lambda_handlers.py", () => {
    expect(API_HANDLER).toBe("commitment_tracker.lambda_handlers.api_handler");
    expect(WORKER_HANDLER).toBe("commitment_tracker.lambda_handlers.worker_handler");
    expect(handlers).toMatch(/^def api_handler\(/m);
    expect(handlers).toMatch(/^def worker_handler\(/m);
  });

  it("names the SSM parameter the backend reads", () => {
    expect(API_KEY_PARAMETER).toBe("/commitment-tracker/prod/ANTHROPIC_API_KEY");
    expect(API_KEY_PARAMETER.startsWith("/")).toBe(true);
  });
});
