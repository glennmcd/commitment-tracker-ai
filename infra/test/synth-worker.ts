// Runs under Node (via tsx), not Bun: CDK's built-in template validation engine takes about 100 seconds to start in
// Bun and 1 second in Node. The tests call this once with every scenario they need and assert on the JSON it prints.
//
// Usage: node --import tsx test/synth-worker.ts '<{"name": {"props": {...}}, ...}>'
import path from "node:path";
import { fileURLToPath } from "node:url";
import { App } from "aws-cdk-lib";
import { ApiStack, type ApiStackProps } from "../lib/api-stack.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const scenarios = JSON.parse(process.argv[2] ?? "{}") as Record<string, { props?: ApiStackProps }>;
const env = { account: "123456789012", region: "us-east-2" };

const out: Record<string, { template: unknown; warnings: string[]; error?: string }> = {};
for (const [name, scenario] of Object.entries(scenarios)) {
  try {
    const app = new App({ analyticsReporting: false });
    new ApiStack(app, "Test", {
      env,
      codePath: path.join(here, "fixtures/lambda"),
      samplesPath: path.join(here, "fixtures/samples"),
      ...scenario.props,
    });
    const stack = app.synth().getStackByName("Test");
    out[name] = {
      template: stack.template,
      warnings: stack.messages.filter((m) => m.level === "warning").map((m) => String(m.entry.data)),
    };
  } catch (error) {
    out[name] = { template: undefined, warnings: [], error: error instanceof Error ? error.message : String(error) };
  }
}
process.stdout.write(`\n@@RESULT@@${JSON.stringify(out)}`);
