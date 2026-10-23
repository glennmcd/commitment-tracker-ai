import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Annotations, ArnFormat, CfnOutput, Duration, RemovalPolicy, Stack, type StackProps, Tags } from "aws-cdk-lib";
import { AccessLogFormat } from "aws-cdk-lib/aws-apigateway";
import { CorsHttpMethod, HttpApi, HttpMethod, HttpStage, LogGroupLogDestination } from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { CfnBudget } from "aws-cdk-lib/aws-budgets";
import { Alarm, ComparisonOperator, MathExpression, Metric, TreatMissingData } from "aws-cdk-lib/aws-cloudwatch";
import { SnsAction } from "aws-cdk-lib/aws-cloudwatch-actions";
import { AttributeType, BillingMode, Table } from "aws-cdk-lib/aws-dynamodb";
import { Rule } from "aws-cdk-lib/aws-events";
import { LambdaFunction as LambdaTarget } from "aws-cdk-lib/aws-events-targets";
import { PolicyStatement, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { Architecture, Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { BlockPublicAccess, Bucket, BucketEncryption, HttpMethods } from "aws-cdk-lib/aws-s3";
import { BucketDeployment, Source } from "aws-cdk-lib/aws-s3-deployment";
import { Topic } from "aws-cdk-lib/aws-sns";
import { EmailSubscription, LambdaSubscription } from "aws-cdk-lib/aws-sns-subscriptions";
import type { Construct } from "constructs";
import {
  API_HANDLER,
  API_KEY_PARAMETER,
  DEFAULT_DAILY_BUDGET_USD,
  DEFAULT_MONTHLY_BUDGET_USD,
  METRIC_NAMESPACE,
  SPEND_FRACTION_METRIC,
  WORKER_HANDLER,
} from "./config.js";

const here = path.dirname(fileURLToPath(import.meta.url));

/** Where `bun run bundle` writes the Lambda code (cdk.json runs it before every synth). */
const DEFAULT_CODE_PATH = path.resolve(here, "../dist/api");

/** The budget kill switch Lambda (sets both functions' reserved concurrency to 0); see addBudget. */
const BUDGET_STOP_CODE_PATH = path.resolve(here, "../lambda/budget-stop");

/** The sample clips `backend/scripts/make_samples.py` writes; deployed to `samples/` in the bucket when present. */
const DEFAULT_SAMPLES_PATH = path.resolve(here, "../../frontend/public/samples");

/** The API's endpoints, as `[method, path]`; the same set as the paths in openapi.json. */
const API_ROUTES: readonly (readonly [HttpMethod, string])[] = [
  [HttpMethod.GET, "/health"],
  [HttpMethod.POST, "/analyze"],
  [HttpMethod.POST, "/uploads"],
  [HttpMethod.POST, "/jobs"],
  [HttpMethod.GET, "/jobs/{job_id}"],
  [HttpMethod.POST, "/feedback"],
  [HttpMethod.GET, "/samples"],
];

/** The site and local development: the only origins the API and the upload bucket accept from a browser. */
export const DEFAULT_ORIGINS = ["https://commitmentai.g26work.com", "http://localhost:3000"] as const;

/** 10 requests per second, burst 20: the demo polls a job once a second, and the per-client limits sit behind this. */
export const DEFAULT_THROTTLE = { rateLimit: 10, burstLimit: 20 } as const;

/** The model the deployed stack runs until Part 3 compares models; the backend's own default stays Opus. */
export const DEFAULT_DEMO_MODEL = "claude-haiku-5-5";

/** Audio and Transcribe output expire after a day, behind the worker's own deletes (ADR 0003). */
export const TRANSIENT_PREFIXES = ["uploads/", "transcripts/"] as const;

export interface ApiStackProps extends StackProps {
  /** Directory holding the Lambda code (the bundle). Defaults to infra/dist/api; tests pass a small fixture. */
  codePath?: string;
  /** Directory of sample clip WAVs to deploy under `samples/`. Skipped, with a warning, when it holds none. */
  samplesPath?: string;
  /** Browser origins allowed by CORS on the API and the bucket. */
  allowedOrigins?: readonly string[];
  /** Daily spend cap enforced by the API, in USD (default 5). */
  dailyBudgetUsd?: number;
  /** The Anthropic model the deployed functions use. */
  model?: string;
  /** Steady and burst requests per second the HTTP API accepts across all callers; API Gateway answers 429 over it. */
  throttle?: { rateLimit: number; burstLimit: number };
  /** Email for the alarms and the cost budget alerts. Without one neither is created and synth prints a warning. */
  alertEmail?: string;
  /**
   * Monthly cost, in USD (default 30). The budget emails at 80% actual and 100% forecast, and at 100% actual it also
   * stops the API and the worker by setting their reserved concurrency to 0. Covers the whole account, which holds
   * only this project (ADR 0007).
   */
  monthlyBudgetUsd?: number;
  /** Caps the API function's concurrent executions. Unset by default: a new account's quota can't afford a reservation. */
  reservedConcurrency?: number;
}

function positiveInteger(name: string, value: number): void {
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
}

export class ApiStack extends Stack {
  readonly httpApiUrl: string;
  readonly bucket: Bucket;
  readonly jobsTable: Table;
  readonly guardrailsTable: Table;
  readonly feedbackTable: Table;
  readonly apiFunction: LambdaFunction;
  readonly workerFunction: LambdaFunction;

  constructor(scope: Construct, id: string, props: ApiStackProps = {}) {
    super(scope, id, props);

    const origins = [...(props.allowedOrigins ?? DEFAULT_ORIGINS)];
    if (origins.length === 0 || origins.some((origin) => !/^https?:\/\/[^/\s]+$/.test(origin))) {
      throw new Error("allowedOrigins must be a non-empty list of origins such as https://example.com");
    }
    const throttle = props.throttle ?? DEFAULT_THROTTLE;
    positiveInteger("throttle.rateLimit", throttle.rateLimit);
    positiveInteger("throttle.burstLimit", throttle.burstLimit);
    if (props.reservedConcurrency !== undefined) positiveInteger("reservedConcurrency", props.reservedConcurrency);
    const dailyBudgetUsd = props.dailyBudgetUsd ?? DEFAULT_DAILY_BUDGET_USD;
    if (!(dailyBudgetUsd > 0)) throw new Error("dailyBudgetUsd must be positive");
    const monthlyBudgetUsd = props.monthlyBudgetUsd ?? DEFAULT_MONTHLY_BUDGET_USD;
    if (!(monthlyBudgetUsd > 0)) throw new Error("monthlyBudgetUsd must be positive");

    Tags.of(this).add("project", "commitment-tracker");

    // Audio and Transcribe output pass through here and are deleted by the worker; the lifecycle rules back that up.
    // Sample clips live under samples/ and are never expired.
    this.bucket = new Bucket(this, "AudioBucket", {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.RETAIN,
      cors: [
        {
          allowedMethods: [HttpMethods.POST],
          allowedOrigins: origins,
          allowedHeaders: ["*"],
          maxAge: 3000,
        },
      ],
      lifecycleRules: TRANSIENT_PREFIXES.map((prefix) => ({
        id: `Expire${prefix.replace("/", "")}`,
        prefix,
        expiration: Duration.days(1),
        abortIncompleteMultipartUploadAfter: Duration.days(1),
      })),
    });

    // Jobs and counters expire on their own (TTL), so losing either table loses nothing that matters.
    this.jobsTable = new Table(this, "JobsTable", {
      partitionKey: { name: "id", type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expires_at",
      removalPolicy: RemovalPolicy.DESTROY,
    });
    this.guardrailsTable = new Table(this, "GuardrailsTable", {
      partitionKey: { name: "pk", type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expires_at",
      removalPolicy: RemovalPolicy.DESTROY,
    });
    // Votes have no expires_at and are kept; consented transcripts carry one and go after 90 days.
    this.feedbackTable = new Table(this, "FeedbackTable", {
      partitionKey: { name: "pk", type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expires_at",
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const code = Code.fromAsset(props.codePath ?? DEFAULT_CODE_PATH);
    const logs = (logId: string) =>
      new LogGroup(this, logId, { retention: RetentionDays.TWO_WEEKS, removalPolicy: RemovalPolicy.DESTROY });
    const common = {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      memorySize: 1024,
      code,
    };
    const sharedEnvironment = {
      AUDIO_BUCKET: this.bucket.bucketName,
      JOBS_TABLE: this.jobsTable.tableName,
      GUARDRAILS_TABLE: this.guardrailsTable.tableName,
      ANTHROPIC_API_KEY_PARAMETER: API_KEY_PARAMETER,
      EXTRACTOR_MODEL: props.model ?? DEFAULT_DEMO_MODEL,
      DAILY_BUDGET_USD: String(dailyBudgetUsd),
    };

    // The worker finishes jobs: Transcribe's completion event and text jobs. A model call can take a while, and one
    // retry of a failed asynchronous invoke is enough because the worker only acts on a job that is waiting.
    this.workerFunction = new LambdaFunction(this, "WorkerFunction", {
      ...common,
      handler: WORKER_HANDLER,
      timeout: Duration.seconds(120),
      retryAttempts: 1,
      maxEventAge: Duration.minutes(10),
      logGroup: logs("WorkerFunctionLogs"),
      environment: sharedEnvironment,
    });

    this.apiFunction = new LambdaFunction(this, "ApiFunction", {
      ...common,
      handler: API_HANDLER,
      // API Gateway gives an integration at most 29 seconds, so a longer Lambda timeout could never be used.
      timeout: Duration.seconds(29),
      reservedConcurrentExecutions: props.reservedConcurrency,
      logGroup: logs("ApiFunctionLogs"),
      environment: {
        ...sharedEnvironment,
        FEEDBACK_TABLE: this.feedbackTable.tableName,
        WORKER_FUNCTION_NAME: this.workerFunction.functionName,
      },
    });

    this.grantApi();
    this.grantWorker();

    // Transcribe's completion event finishes the job; the rule matches only our jobs (ct-<id>).
    new Rule(this, "TranscribeFinished", {
      description: "A Transcribe job of ours finished or failed",
      eventPattern: {
        source: ["aws.transcribe"],
        detailType: ["Transcribe Job State Change"],
        detail: {
          TranscriptionJobStatus: ["COMPLETED", "FAILED"],
          TranscriptionJobName: [{ prefix: "ct-" }],
        },
      },
      targets: [new LambdaTarget(this.workerFunction, { retryAttempts: 1 })],
    });

    const httpApi = new HttpApi(this, "HttpApi", {
      apiName: "commitment-tracker-api",
      createDefaultStage: false,
      corsPreflight: {
        allowOrigins: origins,
        allowMethods: [CorsHttpMethod.GET, CorsHttpMethod.POST, CorsHttpMethod.OPTIONS],
        allowHeaders: ["content-type"],
        exposeHeaders: ["retry-after", "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"],
        maxAge: Duration.hours(1),
      },
    });
    // One route per endpoint, never a catch-all: with a $default route API Gateway forwards a browser's OPTIONS
    // preflight to the Lambda, which answers 405, and the browser blocks the real request. With no route matching
    // OPTIONS, API Gateway answers the preflight itself from corsPreflight. test/stacks.test.ts keeps this list equal
    // to the paths in openapi.json.
    const integration = new HttpLambdaIntegration("ApiIntegration", this.apiFunction);
    for (const [method, routePath] of API_ROUTES) {
      httpApi.addRoutes({ path: routePath, methods: [method], integration });
    }
    new HttpStage(this, "DefaultStage", {
      httpApi,
      stageName: "$default",
      autoDeploy: true,
      throttle,
      accessLogSettings: {
        destination: new LogGroupLogDestination(logs("ApiAccessLogs")),
        format: AccessLogFormat.jsonWithStandardFields(),
      },
    });
    this.httpApiUrl = httpApi.apiEndpoint;

    this.addSamples(props.samplesPath ?? DEFAULT_SAMPLES_PATH);

    if (props.alertEmail) {
      this.addAlarms(httpApi, props.alertEmail);
      this.addBudget(props.alertEmail, monthlyBudgetUsd);
    } else {
      Annotations.of(this).addWarningV2(
        "commitment-tracker:no-budget",
        "No alertEmail given, so no cost budget, kill switch or alarms are created. Pass -c alertEmail=you@example.com before deploying.",
      );
    }

    new CfnOutput(this, "ApiUrl", { value: httpApi.apiEndpoint, description: "NEXT_PUBLIC_API_BASE_URL for the site" });
    new CfnOutput(this, "AudioBucketName", { value: this.bucket.bucketName });
    new CfnOutput(this, "ApiFunctionName", { value: this.apiFunction.functionName });
    new CfnOutput(this, "WorkerFunctionName", { value: this.workerFunction.functionName });
    new CfnOutput(this, "ApiKeyParameter", {
      value: API_KEY_PARAMETER,
      description: "Create this SecureString parameter with the Anthropic key before the first request",
    });
  }

  private objects(...prefixes: string[]): string[] {
    return prefixes.map((prefix) => `${this.bucket.bucketArn}/${prefix}`);
  }

  private apiKeyParameterArn(): string {
    return this.formatArn({
      service: "ssm",
      resource: "parameter",
      resourceName: API_KEY_PARAMETER.slice(1),
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    });
  }

  /**
   * The API's role, statement by statement (test/iam.test.ts asserts each). Transcribe reads the audio and writes its
   * output with the *caller's* credentials, so the API role needs those two object permissions as well.
   */
  private grantApi(): void {
    const api = this.apiFunction;
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "ReadAndDeleteUploads",
        actions: ["s3:GetObject", "s3:DeleteObject"],
        resources: this.objects("uploads/*"),
      }),
    );
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "TranscribeReadsSamples",
        actions: ["s3:GetObject"],
        resources: this.objects("samples/*"),
      }),
    );
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "TranscribeWritesOutput",
        actions: ["s3:PutObject"],
        resources: this.objects("transcripts/*"),
      }),
    );
    // Job-level Transcribe actions can't be limited to a resource.
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "StartTranscription",
        actions: ["transcribe:StartTranscriptionJob"],
        resources: ["*"],
      }),
    );
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "JobsAndGuardrails",
        actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
        resources: [this.jobsTable.tableArn, this.guardrailsTable.tableArn],
      }),
    );
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "Feedback",
        actions: ["dynamodb:PutItem", "dynamodb:DeleteItem"],
        resources: [this.feedbackTable.tableArn],
      }),
    );
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "InvokeWorker",
        actions: ["lambda:InvokeFunction"],
        resources: [this.workerFunction.functionArn],
      }),
    );
    api.addToRolePolicy(
      new PolicyStatement({
        sid: "ReadApiKey",
        actions: ["ssm:GetParameter"],
        resources: [this.apiKeyParameterArn()],
      }),
    );
  }

  /** The worker's role: finish jobs, delete audio and Transcribe output, count spend. */
  private grantWorker(): void {
    const worker = this.workerFunction;
    worker.addToRolePolicy(
      new PolicyStatement({
        sid: "ReadAndDeleteAudioAndOutput",
        actions: ["s3:GetObject", "s3:DeleteObject"],
        resources: this.objects("uploads/*", "transcripts/*"),
      }),
    );
    worker.addToRolePolicy(
      new PolicyStatement({
        sid: "DeleteTranscriptionJobs",
        actions: ["transcribe:DeleteTranscriptionJob"],
        resources: ["*"],
      }),
    );
    worker.addToRolePolicy(
      new PolicyStatement({
        sid: "Jobs",
        actions: ["dynamodb:GetItem", "dynamodb:PutItem"],
        resources: [this.jobsTable.tableArn],
      }),
    );
    worker.addToRolePolicy(
      new PolicyStatement({
        sid: "CountSpend",
        actions: ["dynamodb:UpdateItem"],
        resources: [this.guardrailsTable.tableArn],
      }),
    );
    worker.addToRolePolicy(
      new PolicyStatement({
        sid: "ReadApiKey",
        actions: ["ssm:GetParameter"],
        resources: [this.apiKeyParameterArn()],
      }),
    );
  }

  /**
   * Alarms notify the alert email: any unhandled error in the worker (handled failures end as failed jobs instead),
   * a 5xx rate over 5% of at least ten requests, and the day's spending reaching 80% of the cap. The spend metric is
   * written by the backend as an embedded-metric-format log line (guardrails/metrics.py).
   */
  private addAlarms(httpApi: HttpApi, email: string): void {
    const alerts = new Topic(this, "AlertsTopic");
    alerts.addSubscription(new EmailSubscription(email));
    const notify = new SnsAction(alerts);
    const period = Duration.minutes(5);
    const make = (alarm: Alarm) => {
      alarm.addAlarmAction(notify);
      return alarm;
    };

    make(
      new Alarm(this, "WorkerErrorsAlarm", {
        alarmDescription: "The worker raised an error it did not handle",
        metric: this.workerFunction.metricErrors({ period, statistic: "Sum" }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      }),
    );

    const errors = httpApi.metricServerError({ period, statistic: "Sum" });
    const requests = httpApi.metricCount({ period, statistic: "Sum" });
    make(
      new Alarm(this, "Api5xxAlarm", {
        alarmDescription: "More than 5% of API requests failed with a 5xx (with at least ten requests)",
        metric: new MathExpression({
          expression: "IF(requests >= 10, 100 * errors / requests, 0)",
          usingMetrics: { errors, requests },
          label: "5xx percent",
          period,
        }),
        threshold: 5,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      }),
    );

    make(
      new Alarm(this, "SpendFractionAlarm", {
        alarmDescription: "The day's spending reached 80% of the daily cap",
        metric: new Metric({
          namespace: METRIC_NAMESPACE,
          metricName: SPEND_FRACTION_METRIC,
          statistic: "Maximum",
          period,
        }),
        threshold: 0.8,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      }),
    );
  }

  /**
   * The monthly budget and its kill switch. At 100% actual spend the budget publishes to a topic and a small Lambda
   * sets both functions' reserved concurrency to 0, which stops every invocation (an SCP cannot: API Gateway calls
   * Lambda as a service principal). The topic policy lets AWS Budgets in this account publish (and no other account).
   * Undo with `aws lambda delete-function-concurrency` on each function. The logical ids BudgetStopFunction and
   * BudgetStopTopic are protected by name in infra/scp/commitment-tracker-guardrails.json.
   */
  private addBudget(email: string, monthlyUsd: number): void {
    const subscribers = [{ subscriptionType: "EMAIL", address: email }];

    const stopTopic = new Topic(this, "BudgetStopTopic");
    stopTopic.addToResourcePolicy(
      new PolicyStatement({
        actions: ["sns:Publish"],
        principals: [new ServicePrincipal("budgets.amazonaws.com")],
        resources: [stopTopic.topicArn],
        conditions: {
          StringEquals: { "aws:SourceAccount": this.account },
          ArnLike: { "aws:SourceArn": `arn:${this.partition}:budgets::${this.account}:*` },
        },
      }),
    );
    const stopFunction = new LambdaFunction(this, "BudgetStopFunction", {
      code: Code.fromAsset(BUDGET_STOP_CODE_PATH),
      handler: "index.handler",
      runtime: Runtime.NODEJS_22_X,
      architecture: Architecture.ARM_64,
      memorySize: 128,
      timeout: Duration.seconds(30),
      logGroup: new LogGroup(this, "BudgetStopLogs", {
        retention: RetentionDays.TWO_WEEKS,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
      environment: { FUNCTION_NAMES: [this.apiFunction.functionName, this.workerFunction.functionName].join(",") },
    });
    stopFunction.addToRolePolicy(
      new PolicyStatement({
        sid: "StopTheFunctions",
        actions: ["lambda:PutFunctionConcurrency"],
        resources: [this.apiFunction.functionArn, this.workerFunction.functionArn],
      }),
    );
    stopTopic.addSubscription(new LambdaSubscription(stopFunction));

    // No budgetName on purpose: budget names are unique per account, and CloudFormation creates a replacement before it
    // deletes the old budget, so a fixed name makes every replacement fail. Left out, AWS generates a unique name.
    new CfnBudget(this, "MonthlyBudget", {
      budget: {
        budgetType: "COST",
        timeUnit: "MONTHLY",
        budgetLimit: { amount: monthlyUsd, unit: "USD" },
      },
      notificationsWithSubscribers: [
        {
          notification: {
            notificationType: "ACTUAL",
            comparisonOperator: "GREATER_THAN",
            threshold: 80,
            thresholdType: "PERCENTAGE",
          },
          subscribers,
        },
        {
          notification: {
            notificationType: "FORECASTED",
            comparisonOperator: "GREATER_THAN",
            threshold: 100,
            thresholdType: "PERCENTAGE",
          },
          subscribers,
        },
        {
          notification: {
            notificationType: "ACTUAL",
            comparisonOperator: "GREATER_THAN",
            threshold: 100,
            thresholdType: "PERCENTAGE",
          },
          subscribers: [...subscribers, { subscriptionType: "SNS", address: stopTopic.topicArn }],
        },
      ],
    });
  }

  /** Sample clips go to samples/ from the repo. They arrive after the owner runs the Polly script, so no clips is fine. */
  private addSamples(samplesPath: string): void {
    const hasClips = existsSync(samplesPath) && readdirSync(samplesPath).some((name) => name.endsWith(".wav"));
    if (!hasClips) {
      Annotations.of(this).addWarningV2(
        "commitment-tracker:no-samples",
        `No sample clips in ${samplesPath}, so none are deployed. Run backend/scripts/make_samples.py first.`,
      );
      return;
    }
    new BucketDeployment(this, "SampleClips", {
      sources: [Source.asset(samplesPath)],
      destinationBucket: this.bucket,
      destinationKeyPrefix: "samples",
      prune: true,
    });
  }
}
