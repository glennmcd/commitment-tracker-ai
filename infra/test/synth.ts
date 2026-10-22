import path from "node:path";
import { fileURLToPath } from "node:url";
import { Template } from "aws-cdk-lib/assertions";
import type { ApiStackProps } from "../lib/api-stack.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const infraRoot = path.join(here, "..");

export const ACCOUNT = "123456789012";
export const REGION = "us-east-2";

const api = (props: ApiStackProps = {}) => ({ props });

/** Every stack the tests need, synthesized together in one Node process (see synth-worker.ts for why not in Bun). */
export const SCENARIOS = {
  defaults: api(),
  custom: api({
    dailyBudgetUsd: 2.5,
    model: "claude-sonnet-5-5",
    allowedOrigins: ["https://example.com"],
    throttle: { rateLimit: 5, burstLimit: 10 },
    reservedConcurrency: 3,
  }),
  noSamples: api({ samplesPath: path.join(here, "fixtures/does-not-exist") }),
  badOriginPath: api({ allowedOrigins: ["https://example.com/app"] }),
  badOriginEmpty: api({ allowedOrigins: [] }),
  badThrottleZero: api({ throttle: { rateLimit: 0, burstLimit: 10 } }),
  badThrottleFraction: api({ throttle: { rateLimit: 5, burstLimit: 7.5 } }),
  badConcurrency: api({ reservedConcurrency: 0 }),
  badBudget: api({ dailyBudgetUsd: 0 }),
} satisfies Record<string, { props: ApiStackProps }>;

export interface Scenario {
  template: Template;
  warnings: string[];
  error?: string;
}

let cached: Record<keyof typeof SCENARIOS, Scenario> | undefined;

export function synthAll(): Record<keyof typeof SCENARIOS, Scenario> {
  if (cached) return cached;
  const run = Bun.spawnSync(["node", "--import", "tsx", "test/synth-worker.ts", JSON.stringify(SCENARIOS)], {
    cwd: infraRoot,
    env: { ...process.env },
  });
  const stdout = run.stdout.toString();
  const marker = stdout.lastIndexOf("@@RESULT@@");
  if (run.exitCode !== 0 || marker < 0) {
    throw new Error(`synth-worker failed (exit ${run.exitCode}): ${run.stderr.toString() || stdout}`);
  }
  const parsed = JSON.parse(stdout.slice(marker + "@@RESULT@@".length)) as Record<
    string,
    { template?: object; warnings: string[]; error?: string }
  >;
  const result: Record<string, Scenario> = {};
  for (const [name, value] of Object.entries(parsed)) {
    result[name] = {
      // A scenario that threw has no template; assertions on it only look at `error`.
      template: Template.fromJSON(value.template ?? { Resources: {} }),
      warnings: value.warnings,
      error: value.error,
    };
  }
  cached = result as Record<keyof typeof SCENARIOS, Scenario>;
  return cached;
}

type Json = Record<string, unknown>;

/** A logical id without CDK's 8-hex-digit suffix: AudioBucketA1B2C3D4 -> AudioBucket. */
function friendly(logicalId: string): string {
  return logicalId.replace(/[0-9A-F]{8}$/, "");
}

/**
 * An IAM resource or other template value as readable text, so assertions can say what a statement points at:
 * `{ "Fn::GetAtt": ["AudioBucketAB12CD34", "Arn"] }` becomes `{AudioBucket.Arn}`, and a Fn::Join of that and
 * "/uploads/*" becomes `{AudioBucket.Arn}/uploads/*`.
 */
export function render(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const v = value as Json;
    if (Array.isArray(v["Fn::GetAtt"])) {
      const [id, attr] = v["Fn::GetAtt"] as [string, string];
      return `{${friendly(id)}.${attr}}`;
    }
    if (typeof v.Ref === "string") return v.Ref.startsWith("AWS::") ? `{${v.Ref}}` : `{${friendly(v.Ref)}}`;
    if (Array.isArray(v["Fn::Join"])) {
      const [separator, parts] = v["Fn::Join"] as [string, unknown[]];
      return parts.map(render).join(separator);
    }
  }
  return JSON.stringify(value);
}

export interface Statement {
  sid?: string;
  effect: string;
  actions: string[];
  resources: string[];
}

/** The statements of the inline policies attached to the role of the function with the given logical-id prefix. */
export function rolePolicyStatements(template: Template, functionId: string): Statement[] {
  const functions = template.findResources("AWS::Lambda::Function");
  const fn = Object.entries(functions).find(([id]) => friendly(id) === functionId);
  if (!fn) throw new Error(`no function ${functionId}`);
  const roleRef = (fn[1].Properties as Json).Role as { "Fn::GetAtt": [string, string] };
  const roleId = roleRef["Fn::GetAtt"][0];
  const statements: Statement[] = [];
  for (const policy of Object.values(template.findResources("AWS::IAM::Policy"))) {
    const props = policy.Properties as { Roles: { Ref: string }[]; PolicyDocument: { Statement: Json[] } };
    if (!props.Roles.some((role) => role.Ref === roleId)) continue;
    for (const s of props.PolicyDocument.Statement) {
      const list = (x: unknown): unknown[] => (Array.isArray(x) ? x : x === undefined ? [] : [x]);
      statements.push({
        sid: s.Sid as string | undefined,
        effect: s.Effect as string,
        actions: list(s.Action).map(String).sort(),
        resources: list(s.Resource).map(render).sort(),
      });
    }
  }
  return statements;
}
