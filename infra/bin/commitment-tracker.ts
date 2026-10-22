import { App } from "aws-cdk-lib";
import { positiveNumberContext } from "../lib/config.js";

const app = new App();

// Spending limits are set at deploy time:
//   cdk deploy -c dailyBudgetUsd=5 -c monthlyBudgetUsd=30 -c alertEmail=you@example.com
// Reading them here makes a bad value fail the synth before any stack is built.
positiveNumberContext(app.node, "dailyBudgetUsd");
positiveNumberContext(app.node, "monthlyBudgetUsd");

// The stacks are added by the next commits: the API stack (bucket, tables, functions, EventBridge rule), the budget
// kill switch and alarms, and the Amplify web stack. Each takes its env from the credentials the CDK CLI runs with
// (CDK_DEFAULT_ACCOUNT) and REGION in lib/config.ts, so no account id is committed.
app.synth();
