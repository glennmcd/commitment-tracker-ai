import { App } from "aws-cdk-lib";
import { ApiStack } from "../lib/api-stack.js";
import { positiveNumberContext, REGION } from "../lib/config.js";
import { WebStack } from "../lib/web-stack.js";

const app = new App();

// Everything lives in the project's one AWS Region. The account comes from the credentials the CDK CLI runs with
// (CDK_DEFAULT_ACCOUNT), so no account id is committed.
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: REGION };

// Spending limits are set at deploy time:
//   cdk deploy -c dailyBudgetUsd=5 -c monthlyBudgetUsd=30 -c alertEmail=you@example.com
const dailyBudgetUsd = positiveNumberContext(app.node, "dailyBudgetUsd");
const monthlyBudgetUsd = positiveNumberContext(app.node, "monthlyBudgetUsd");
const alertEmail: unknown = app.node.tryGetContext("alertEmail");

// -c throttleRate=N sets the API's steady requests per second (default 10); -c throttleBurst=M the burst (default 2N).
const throttleRate = positiveNumberContext(app.node, "throttleRate");
const throttleBurst = positiveNumberContext(app.node, "throttleBurst");
if (throttleBurst !== undefined && throttleRate === undefined) {
  throw new Error("context throttleBurst needs throttleRate as well");
}
const throttle =
  throttleRate === undefined ? undefined : { rateLimit: throttleRate, burstLimit: throttleBurst ?? throttleRate * 2 };

// The stack id is fixed: the guardrail SCP protects "CommitmentTrackerApi-BudgetStopFunction*" by name.
const api = new ApiStack(app, "CommitmentTrackerApi", {
  env,
  description: "Commitment Tracker AI API: Lambda behind an API Gateway HTTP API, Transcribe, S3 and DynamoDB",
  dailyBudgetUsd,
  monthlyBudgetUsd,
  alertEmail: typeof alertEmail === "string" ? alertEmail : undefined,
  throttle,
  reservedConcurrency: positiveNumberContext(app.node, "reservedConcurrency"),
});

// The site's custom domain lives in cdk.json's context, so every deploy carries it (a deploy without it would delete
// the domain association). A -c override arrives as a JSON string.
const rawDomain = app.node.tryGetContext("customDomain");
const customDomain = typeof rawDomain === "string" ? JSON.parse(rawDomain) : rawDomain;

// The site on Amplify Hosting, built from GitHub as a static export:
//   cdk deploy CommitmentTrackerWeb -c repository=https://github.com/<owner>/<repo> -c githubTokenSecretName=<secret>
const text = (name: string): string | undefined => {
  const value: unknown = app.node.tryGetContext(name);
  return typeof value === "string" ? value : undefined;
};
new WebStack(app, "CommitmentTrackerWeb", {
  env,
  description: "Commitment Tracker AI site: a Next.js static export on Amplify Hosting",
  apiUrl: api.httpApiUrl,
  repository: text("repository"),
  githubTokenSecretName: text("githubTokenSecretName"),
  branch: text("branch"),
  customDomain,
});
