import { describe, expect, it } from "bun:test";
import { Match } from "aws-cdk-lib/assertions";
import { render, synthAll } from "./synth.js";

const { defaults, budget, budgetDefault } = synthAll();

type Json = Record<string, unknown>;

function resources(template: typeof budget.template, type: string): Record<string, Json> {
  return template.findResources(type) as Record<string, Json>;
}

const named = (all: Record<string, Json>, prefix: string): [string, Json] => {
  const found = Object.entries(all).find(([id]) => id.replace(/[0-9A-F]{8}$/, "") === prefix);
  if (!found) throw new Error(`no ${prefix}`);
  return found;
};

describe("the monthly budget", () => {
  it("is 30 USD by default and 25 when asked, over the whole account", () => {
    budgetDefault.template.hasResourceProperties("AWS::Budgets::Budget", {
      Budget: { BudgetType: "COST", TimeUnit: "MONTHLY", BudgetLimit: { Amount: 30, Unit: "USD" } },
    });
    budget.template.hasResourceProperties("AWS::Budgets::Budget", {
      Budget: { BudgetLimit: { Amount: 25, Unit: "USD" } },
    });
  });

  it("emails at 80% actual and 100% forecast, and at 100% actual also trips the kill switch", () => {
    const [, resource] = named(resources(budget.template, "AWS::Budgets::Budget"), "MonthlyBudget");
    const notifications = (
      resource.Properties as {
        NotificationsWithSubscribers: {
          Notification: { NotificationType: string; Threshold: number };
          Subscribers: { SubscriptionType: string; Address: unknown }[];
        }[];
      }
    ).NotificationsWithSubscribers;
    expect(notifications.map((n) => [n.Notification.NotificationType, n.Notification.Threshold])).toEqual([
      ["ACTUAL", 80],
      ["FORECASTED", 100],
      ["ACTUAL", 100],
    ]);
    expect(notifications.map((n) => n.Subscribers.map((s) => s.SubscriptionType))).toEqual([
      ["EMAIL"],
      ["EMAIL"],
      ["EMAIL", "SNS"],
    ]);
    for (const n of notifications) expect(n.Subscribers[0]?.Address).toBe("me@example.com");
  });
});

describe("the kill switch", () => {
  it("lets AWS Budgets in this account publish to its topic, and nobody else", () => {
    const [, policy] = named(resources(budget.template, "AWS::SNS::TopicPolicy"), "BudgetStopTopicPolicy");
    const statements = (policy.Properties as { PolicyDocument: { Statement: Json[] } }).PolicyDocument.Statement;
    expect(statements).toHaveLength(1);
    const statement = statements[0] as Json;
    expect(statement).toMatchObject({
      Action: "sns:Publish",
      Effect: "Allow",
      Principal: { Service: "budgets.amazonaws.com" },
    });
    const condition = statement.Condition as { StringEquals: Json; ArnLike: Json };
    expect(condition.StringEquals).toEqual({ "aws:SourceAccount": "123456789012" });
    expect(render(condition.ArnLike["aws:SourceArn"])).toBe("arn:{AWS::Partition}:budgets::123456789012:*");
  });

  it("runs a Node function subscribed to that topic, with the logical ids the SCP protects", () => {
    const functions = resources(budget.template, "AWS::Lambda::Function");
    const [, stop] = named(functions, "BudgetStopFunction");
    expect(stop.Properties).toMatchObject({
      Runtime: "nodejs22.x",
      Architectures: ["arm64"],
      Handler: "index.handler",
      Timeout: 30,
    });
    named(resources(budget.template, "AWS::SNS::Topic"), "BudgetStopTopic");
    budget.template.hasResourceProperties("AWS::SNS::Subscription", { Protocol: "lambda" });
  });

  it("is told both function names", () => {
    const [, stop] = named(resources(budget.template, "AWS::Lambda::Function"), "BudgetStopFunction");
    const names = (stop.Properties as { Environment: { Variables: { FUNCTION_NAMES: unknown } } }).Environment.Variables
      .FUNCTION_NAMES;
    expect(render(names)).toBe("{ApiFunction},{WorkerFunction}");
  });
});

describe("the alarms", () => {
  const alarms = resources(budget.template, "AWS::CloudWatch::Alarm");

  it("are three, all notifying the alert topic", () => {
    expect(Object.keys(alarms)).toHaveLength(3);
    for (const alarm of Object.values(alarms)) {
      expect((alarm.Properties as { AlarmActions: unknown[] }).AlarmActions).toHaveLength(1);
      expect(alarm.Properties).toMatchObject({ TreatMissingData: "notBreaching" });
    }
  });

  it("send alerts to the alert email", () => {
    budget.template.hasResourceProperties("AWS::SNS::Subscription", {
      Protocol: "email",
      Endpoint: "me@example.com",
    });
  });

  it("fire on any unhandled worker error", () => {
    budget.template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "AWS/Lambda",
      MetricName: "Errors",
      Statistic: "Sum",
      Period: 300,
      Threshold: 1,
      ComparisonOperator: "GreaterThanOrEqualToThreshold",
    });
  });

  it("fire when over 5% of at least ten API requests fail with a 5xx", () => {
    budget.template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Threshold: 5,
      ComparisonOperator: "GreaterThanThreshold",
      Metrics: Match.arrayWith([
        Match.objectLike({ Expression: "IF(requests >= 10, 100 * errors / requests, 0)", ReturnData: true }),
        Match.objectLike({
          Id: "errors",
          MetricStat: Match.objectLike({ Metric: Match.objectLike({ MetricName: "5xx" }) }),
        }),
        Match.objectLike({
          Id: "requests",
          MetricStat: Match.objectLike({ Metric: Match.objectLike({ MetricName: "Count" }) }),
        }),
      ]),
    });
  });

  it("fire when the day's spending reaches 80% of the cap, on the metric the backend writes", () => {
    budget.template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "CommitmentTracker",
      MetricName: "DailySpendFraction",
      Statistic: "Maximum",
      Threshold: 0.8,
      ComparisonOperator: "GreaterThanOrEqualToThreshold",
    });
  });
});

describe("without an alert email", () => {
  it("creates no budget, kill switch or alarms, and warns", () => {
    expect(resources(defaults.template, "AWS::Budgets::Budget")).toEqual({});
    expect(resources(defaults.template, "AWS::CloudWatch::Alarm")).toEqual({});
    expect(resources(defaults.template, "AWS::SNS::Topic")).toEqual({});
    expect(defaults.warnings.some((w) => w.includes("No alertEmail"))).toBe(true);
  });
});
