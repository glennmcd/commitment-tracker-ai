import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Match } from "aws-cdk-lib/assertions";
import { API_HANDLER, API_KEY_PARAMETER, WORKER_HANDLER } from "../lib/config.js";
import { synthAll } from "./synth.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const settingsPy = readFileSync(path.join(here, "../../backend/src/commitment_tracker/settings.py"), "utf8");

const { defaults, custom, noSamples, ...rest } = synthAll();

function envOf(template: typeof defaults.template, logicalPrefix: string): Record<string, unknown> {
  const functions = template.findResources("AWS::Lambda::Function");
  const entry = Object.entries(functions).find(([id]) => id.startsWith(logicalPrefix));
  if (!entry) throw new Error(`no function ${logicalPrefix}`);
  return (entry[1].Properties as { Environment: { Variables: Record<string, unknown> } }).Environment.Variables;
}

describe("the audio bucket", () => {
  it("is private, encrypted and TLS-only", () => {
    defaults.template.hasResourceProperties("AWS::S3::Bucket", {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [{ ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } }],
      },
    });
    defaults.template.hasResourceProperties("AWS::S3::BucketPolicy", {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({ Effect: "Deny", Action: "s3:*", Condition: { Bool: { "aws:SecureTransport": "false" } } }),
        ]),
      },
    });
  });

  it("expires uploads and transcripts after a day, and nothing else", () => {
    const [bucket] = Object.values(defaults.template.findResources("AWS::S3::Bucket"));
    if (!bucket) throw new Error("no bucket");
    const rules = (bucket.Properties as { LifecycleConfiguration: { Rules: Record<string, unknown>[] } })
      .LifecycleConfiguration.Rules;
    expect(rules.map((r) => r.Prefix).sort()).toEqual(["transcripts/", "uploads/"]);
    for (const rule of rules) {
      expect(rule).toMatchObject({
        Status: "Enabled",
        ExpirationInDays: 1,
        AbortIncompleteMultipartUpload: { DaysAfterInitiation: 1 },
      });
    }
  });

  it("accepts browser uploads by POST from the site and from localhost only", () => {
    defaults.template.hasResourceProperties("AWS::S3::Bucket", {
      CorsConfiguration: {
        CorsRules: [
          {
            AllowedMethods: ["POST"],
            AllowedOrigins: ["https://commitmentai.g26work.com", "http://localhost:3000"],
            AllowedHeaders: ["*"],
          },
        ],
      },
    });
  });

  it("is kept when the stack is deleted", () => {
    const [bucket] = Object.values(defaults.template.findResources("AWS::S3::Bucket"));
    expect(bucket).toMatchObject({ DeletionPolicy: "Retain" });
  });
});

describe("the tables", () => {
  it("are on demand, with a TTL attribute", () => {
    const tables = Object.values(defaults.template.findResources("AWS::DynamoDB::Table"));
    expect(tables).toHaveLength(3);
    for (const table of tables) {
      expect(table.Properties).toMatchObject({
        BillingMode: "PAY_PER_REQUEST",
        TimeToLiveSpecification: { AttributeName: "expires_at", Enabled: true },
      });
    }
  });

  it("key jobs by id and the others by pk, as the backend does", () => {
    const keys = Object.fromEntries(
      Object.entries(defaults.template.findResources("AWS::DynamoDB::Table")).map(([id, t]) => [
        id.replace(/[0-9A-F]{8}$/, ""),
        (t.Properties as { KeySchema: { AttributeName: string }[] }).KeySchema.map((k) => k.AttributeName),
      ]),
    );
    expect(keys).toEqual({ JobsTable: ["id"], GuardrailsTable: ["pk"], FeedbackTable: ["pk"] });
  });

  it("delete the ephemeral tables with the stack and keep the votes", () => {
    const policies = Object.fromEntries(
      Object.entries(defaults.template.findResources("AWS::DynamoDB::Table")).map(([id, t]) => [
        id.replace(/[0-9A-F]{8}$/, ""),
        t.DeletionPolicy,
      ]),
    );
    expect(policies).toEqual({ JobsTable: "Delete", GuardrailsTable: "Delete", FeedbackTable: "Retain" });
  });
});

describe("the functions", () => {
  it("run Python 3.12 on arm64 with the handlers the backend defines", () => {
    defaults.template.hasResourceProperties("AWS::Lambda::Function", {
      Runtime: "python3.12",
      Architectures: ["arm64"],
      Handler: API_HANDLER,
      Timeout: 29,
    });
    defaults.template.hasResourceProperties("AWS::Lambda::Function", {
      Runtime: "python3.12",
      Architectures: ["arm64"],
      Handler: WORKER_HANDLER,
      Timeout: 120,
    });
  });

  it("get the demo model, the cap and the parameter name, never the key", () => {
    for (const prefix of ["ApiFunction", "WorkerFunction"]) {
      const env = envOf(defaults.template, prefix);
      expect(env).toMatchObject({
        EXTRACTOR_MODEL: "claude-haiku-5-5",
        DAILY_BUDGET_USD: "5",
        ANTHROPIC_API_KEY_PARAMETER: API_KEY_PARAMETER,
      });
      expect(Object.keys(env)).not.toContain("ANTHROPIC_API_KEY");
    }
  });

  it("point the API at the worker and the feedback table, and the worker at neither", () => {
    expect(Object.keys(envOf(defaults.template, "ApiFunction"))).toContain("WORKER_FUNCTION_NAME");
    expect(Object.keys(envOf(defaults.template, "ApiFunction"))).toContain("FEEDBACK_TABLE");
    expect(Object.keys(envOf(defaults.template, "WorkerFunction"))).not.toContain("WORKER_FUNCTION_NAME");
    expect(Object.keys(envOf(defaults.template, "WorkerFunction"))).not.toContain("FEEDBACK_TABLE");
  });

  it("only set variables that the backend's settings read", () => {
    const fields = new Set([...settingsPy.matchAll(/^\s{4}([a-z_]+):/gm)].map((m) => (m[1] as string).toUpperCase()));
    for (const prefix of ["ApiFunction", "WorkerFunction"]) {
      for (const name of Object.keys(envOf(defaults.template, prefix))) {
        expect(fields.has(name)).toBe(true);
      }
    }
  });

  it("retry a failed asynchronous invoke once, for ten minutes at most", () => {
    defaults.template.hasResourceProperties("AWS::Lambda::EventInvokeConfig", {
      MaximumRetryAttempts: 1,
      MaximumEventAgeInSeconds: 600,
    });
  });

  it("keep two weeks of logs", () => {
    const groups = Object.values(defaults.template.findResources("AWS::Logs::LogGroup"));
    expect(groups.length).toBeGreaterThanOrEqual(3);
    for (const group of groups) expect(group.Properties).toMatchObject({ RetentionInDays: 14 });
  });

  it("takes the model, cap and concurrency from the props", () => {
    expect(envOf(custom.template, "ApiFunction")).toMatchObject({
      EXTRACTOR_MODEL: "claude-sonnet-5-5",
      DAILY_BUDGET_USD: "2.5",
    });
    custom.template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: API_HANDLER,
      ReservedConcurrentExecutions: 3,
    });
    const workers = Object.values(custom.template.findResources("AWS::Lambda::Function")).filter(
      (f) => (f.Properties as { Handler?: string }).Handler === WORKER_HANDLER,
    );
    expect(workers[0]?.Properties).not.toHaveProperty("ReservedConcurrentExecutions");
  });
});

describe("the Transcribe completion rule", () => {
  it("matches finished or failed jobs named ct-<id> and nothing else", () => {
    defaults.template.hasResourceProperties("AWS::Events::Rule", {
      EventPattern: {
        source: ["aws.transcribe"],
        "detail-type": ["Transcribe Job State Change"],
        detail: {
          TranscriptionJobStatus: ["COMPLETED", "FAILED"],
          TranscriptionJobName: [{ prefix: "ct-" }],
        },
      },
    });
  });

  it("targets the worker, retrying once", () => {
    defaults.template.hasResourceProperties("AWS::Events::Rule", {
      Targets: [Match.objectLike({ RetryPolicy: { MaximumRetryAttempts: 1 }, Arn: Match.anyValue() })],
    });
    defaults.template.hasResourceProperties("AWS::Lambda::Permission", {
      Action: "lambda:InvokeFunction",
      Principal: "events.amazonaws.com",
    });
  });
});

describe("the HTTP API", () => {
  it("answers the site and localhost, exposing the rate limit headers", () => {
    defaults.template.hasResourceProperties("AWS::ApiGatewayV2::Api", {
      ProtocolType: "HTTP",
      CorsConfiguration: {
        AllowOrigins: ["https://commitmentai.g26work.com", "http://localhost:3000"],
        AllowMethods: ["GET", "POST", "OPTIONS"],
        AllowHeaders: ["content-type"],
        ExposeHeaders: ["retry-after", "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"],
        MaxAge: 3600,
      },
    });
  });

  it("throttles the default stage and logs access", () => {
    defaults.template.hasResourceProperties("AWS::ApiGatewayV2::Stage", {
      StageName: "$default",
      AutoDeploy: true,
      DefaultRouteSettings: { ThrottlingRateLimit: 10, ThrottlingBurstLimit: 20 },
      AccessLogSettings: Match.objectLike({ DestinationArn: Match.anyValue() }),
    });
    custom.template.hasResourceProperties("AWS::ApiGatewayV2::Stage", {
      DefaultRouteSettings: { ThrottlingRateLimit: 5, ThrottlingBurstLimit: 10 },
    });
  });

  it("follows allowedOrigins", () => {
    custom.template.hasResourceProperties("AWS::ApiGatewayV2::Api", {
      CorsConfiguration: Match.objectLike({ AllowOrigins: ["https://example.com"] }),
    });
  });

  // A catch-all ($default or ANY) route would send a browser's OPTIONS preflight to the Lambda, which answers 405,
  // instead of letting API Gateway answer it from the CORS configuration.
  it("routes exactly the paths in openapi.json, so API Gateway answers CORS preflights itself", () => {
    const spec = JSON.parse(readFileSync(path.join(here, "../../openapi.json"), "utf8")) as {
      paths: Record<string, Record<string, unknown>>;
    };
    const expected = Object.entries(spec.paths)
      .flatMap(([route, methods]) => Object.keys(methods).map((method) => `${method.toUpperCase()} ${route}`))
      .sort();
    const routeKeys = Object.values(defaults.template.findResources("AWS::ApiGatewayV2::Route"))
      .map((r) => (r.Properties as { RouteKey: string }).RouteKey)
      .sort();
    expect(routeKeys).toEqual(expected);
  });
});

describe("the sample clips", () => {
  it("are deployed under samples/ when there are some", () => {
    defaults.template.hasResourceProperties("Custom::CDKBucketDeployment", { DestinationBucketKeyPrefix: "samples" });
    expect(defaults.warnings.filter((w) => w.includes("sample clips"))).toEqual([]);
  });

  it("are skipped with a warning when the directory has none", () => {
    expect(noSamples.template.findResources("Custom::CDKBucketDeployment")).toEqual({});
    expect(noSamples.warnings.some((w) => w.includes("No sample clips"))).toBe(true);
  });
});

describe("the outputs", () => {
  it("give the frontend its API URL and name the parameter to create", () => {
    const outputs = defaults.template.toJSON().Outputs as Record<string, { Value: unknown }>;
    expect(Object.keys(outputs).sort()).toEqual([
      "ApiFunctionName",
      "ApiKeyParameter",
      "ApiUrl",
      "AudioBucketName",
      "WorkerFunctionName",
    ]);
    expect(outputs.ApiKeyParameter?.Value).toBe(API_KEY_PARAMETER);
  });
});

describe("bad props", () => {
  it.each([
    ["badOriginPath", "allowedOrigins must be a non-empty list of origins"],
    ["badOriginEmpty", "allowedOrigins must be a non-empty list of origins"],
    ["badThrottleZero", "throttle.rateLimit must be a positive integer"],
    ["badThrottleFraction", "throttle.burstLimit must be a positive integer"],
    ["badConcurrency", "reservedConcurrency must be a positive integer"],
    ["badBudget", "dailyBudgetUsd must be positive"],
    ["badMonthly", "monthlyBudgetUsd must be positive"],
  ] as const)("%s is refused", (name, message) => {
    expect(rest[name].error).toContain(message);
  });
});

describe("the deploy-time context", () => {
  it("lets -c choose the model, the alert email and the spending limits", () => {
    const app = readFileSync(path.join(here, "../bin/commitment-tracker.ts"), "utf8");
    for (const name of [
      "model",
      "alertEmail",
      "dailyBudgetUsd",
      "monthlyBudgetUsd",
      "throttleRate",
      "reservedConcurrency",
    ]) {
      expect(app).toContain(`"${name}"`);
    }
  });
});

describe("the contract with the SCP", () => {
  it("names the stack CommitmentTrackerApi, as the kill-switch protection assumes", () => {
    const app = readFileSync(path.join(here, "../bin/commitment-tracker.ts"), "utf8");
    expect(app).toContain('new ApiStack(app, "CommitmentTrackerApi"');
    const scp = readFileSync(path.join(here, "../scp/commitment-tracker-guardrails.json"), "utf8");
    expect(scp).toContain("CommitmentTrackerApi-BudgetStopFunction");
  });
});
