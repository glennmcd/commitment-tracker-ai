import { describe, expect, it } from "bun:test";
import { ACCOUNT, REGION, rolePolicyStatements, synthAll } from "./synth.js";

// Every statement of each function's role, spelled out. A widened permission, a new resource or a new action fails
// here until the test is changed on purpose.

const BUCKET = "{AudioBucket.Arn}";
const JOBS = "{JobsTable.Arn}";
const GUARDRAILS = "{GuardrailsTable.Arn}";
const FEEDBACK = "{FeedbackTable.Arn}";
const PARAMETER = `arn:{AWS::Partition}:ssm:${REGION}:${ACCOUNT}:parameter/commitment-tracker/prod/ANTHROPIC_API_KEY`;

/** Statements the tests don't spell out: CDK's log permissions for the function's own log group. */
const isLogs = (actions: string[]) => actions.every((a) => a.startsWith("logs:"));

function bySid(functionId: string, scenario: "defaults" | "budget" = "defaults") {
  const statements = rolePolicyStatements(synthAll()[scenario].template, functionId);
  return {
    all: statements,
    mine: Object.fromEntries(statements.filter((s) => s.sid !== undefined).map((s) => [s.sid as string, s])),
    rest: statements.filter((s) => s.sid === undefined),
  };
}

describe("the API function's role", () => {
  const { mine, rest } = bySid("ApiFunction");

  it("has exactly the statements below and nothing else", () => {
    expect(Object.keys(mine).sort()).toEqual([
      "Feedback",
      "InvokeWorker",
      "JobsAndGuardrails",
      "ReadAndDeleteUploads",
      "ReadApiKey",
      "StartTranscription",
      "TranscribeReadsSamples",
      "TranscribeWritesOutput",
    ]);
    expect(rest.every((s) => isLogs(s.actions))).toBe(true);
  });

  it("reads and deletes uploads only", () => {
    expect(mine.ReadAndDeleteUploads).toMatchObject({
      effect: "Allow",
      actions: ["s3:DeleteObject", "s3:GetObject"],
      resources: [`${BUCKET}/uploads/*`],
    });
  });

  it("lets Transcribe read samples and write its output through the caller's credentials", () => {
    expect(mine.TranscribeReadsSamples).toMatchObject({
      actions: ["s3:GetObject"],
      resources: [`${BUCKET}/samples/*`],
    });
    expect(mine.TranscribeWritesOutput).toMatchObject({
      actions: ["s3:PutObject"],
      resources: [`${BUCKET}/transcripts/*`],
    });
  });

  it("starts Transcribe jobs, an action that can't be limited to a resource", () => {
    expect(mine.StartTranscription).toMatchObject({ actions: ["transcribe:StartTranscriptionJob"], resources: ["*"] });
  });

  it("reads and writes job and guardrail items, and writes feedback", () => {
    expect(mine.JobsAndGuardrails).toMatchObject({
      actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
      resources: [GUARDRAILS, JOBS],
    });
    expect(mine.Feedback).toMatchObject({
      actions: ["dynamodb:DeleteItem", "dynamodb:PutItem"],
      resources: [FEEDBACK],
    });
  });

  it("invokes the worker and reads the one parameter", () => {
    expect(mine.InvokeWorker).toMatchObject({
      actions: ["lambda:InvokeFunction"],
      resources: ["{WorkerFunction.Arn}"],
    });
    expect(mine.ReadApiKey).toMatchObject({ actions: ["ssm:GetParameter"], resources: [PARAMETER] });
  });

  it("allows nothing on the whole account", () => {
    const { all } = bySid("ApiFunction");
    const wide = all.filter((s) => s.resources.includes("*") && !isLogs(s.actions));
    expect(wide.map((s) => s.sid)).toEqual(["StartTranscription"]);
  });
});

describe("the worker function's role", () => {
  const { mine, rest } = bySid("WorkerFunction");

  it("has exactly the statements below and nothing else", () => {
    expect(Object.keys(mine).sort()).toEqual([
      "CountSpend",
      "DeleteTranscriptionJobs",
      "Jobs",
      "ReadAndDeleteAudioAndOutput",
      "ReadApiKey",
    ]);
    expect(rest.every((s) => isLogs(s.actions))).toBe(true);
  });

  it("reads and deletes audio and Transcribe output, never samples", () => {
    expect(mine.ReadAndDeleteAudioAndOutput).toMatchObject({
      actions: ["s3:DeleteObject", "s3:GetObject"],
      resources: [`${BUCKET}/transcripts/*`, `${BUCKET}/uploads/*`],
    });
  });

  it("deletes Transcribe jobs", () => {
    expect(mine.DeleteTranscriptionJobs).toMatchObject({
      actions: ["transcribe:DeleteTranscriptionJob"],
      resources: ["*"],
    });
  });

  it("finishes jobs, counts spend and reads the one parameter", () => {
    expect(mine.Jobs).toMatchObject({ actions: ["dynamodb:GetItem", "dynamodb:PutItem"], resources: [JOBS] });
    expect(mine.CountSpend).toMatchObject({ actions: ["dynamodb:UpdateItem"], resources: [GUARDRAILS] });
    expect(mine.ReadApiKey).toMatchObject({ actions: ["ssm:GetParameter"], resources: [PARAMETER] });
  });

  it("cannot write to the bucket or reach feedback", () => {
    const { all } = bySid("WorkerFunction");
    const actions = all.flatMap((s) => s.actions);
    expect(actions).not.toContain("s3:PutObject");
    expect(all.flatMap((s) => s.resources)).not.toContain(FEEDBACK);
  });
});

describe("the budget kill switch's role", () => {
  const { mine, rest } = bySid("BudgetStopFunction", "budget");

  it("may only set the reserved concurrency of the API and the worker", () => {
    expect(Object.keys(mine)).toEqual(["StopTheFunctions"]);
    expect(mine.StopTheFunctions).toMatchObject({
      effect: "Allow",
      actions: ["lambda:PutFunctionConcurrency"],
      resources: ["{ApiFunction.Arn}", "{WorkerFunction.Arn}"],
    });
    expect(rest.every((s) => isLogs(s.actions))).toBe(true);
  });
});
