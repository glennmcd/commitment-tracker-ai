/**
 * Budget kill switch: sets the reserved concurrency of the API and worker functions to 0, which refuses every
 * invocation until someone runs `aws lambda delete-function-concurrency` on each (docs/deploying.md). It runs when the
 * account budget reaches 100% of its actual spend. It ignores the message, so anyone in the account who can publish to
 * the SNS topic that triggers it can also trip it.
 *
 * Every function is tried even if one fails, and the failure is rethrown afterwards so the invocation is visible and
 * retried. `setConcurrency(functionName, limit)` is injected so tests need no AWS SDK.
 */
export function createHandler({ setConcurrency, functionNames }) {
  const names = (functionNames ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (names.length === 0) throw new Error("FUNCTION_NAMES is not set");
  return async () => {
    const stopped = [];
    const failures = [];
    for (const name of names) {
      try {
        await setConcurrency(name, 0);
        stopped.push(name);
        console.warn(`Budget exceeded: reserved concurrency of ${name} set to 0`);
      } catch (error) {
        failures.push(`${name}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    if (failures.length > 0) throw new Error(`could not stop ${failures.join("; ")}`);
    return { stopped };
  };
}

// The AWS SDK comes from the Lambda runtime, so it is loaded here only, never when the module is imported by a test.
export const handler = async (event) => {
  const { LambdaClient, PutFunctionConcurrencyCommand } = await import("@aws-sdk/client-lambda");
  const client = new LambdaClient({});
  const setConcurrency = (name, limit) =>
    client.send(new PutFunctionConcurrencyCommand({ FunctionName: name, ReservedConcurrentExecutions: limit }));
  return createHandler({ setConcurrency, functionNames: process.env.FUNCTION_NAMES })(event);
};
