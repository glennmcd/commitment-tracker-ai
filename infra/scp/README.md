# Guardrail SCP

`commitment-tracker-guardrails.json` is the service control policy (SCP) for the project's own member account
([ADR 0007](../../docs/decisions/0007-separate-aws-account.md)). It is adapted from FlakeHunter's guardrails. SCPs
are managed from the **management account**, so you run the commands below there. CDK never creates or attaches
this policy.

An SCP only restricts; it grants nothing, and it never applies to the management account itself. Every statement
exempts the AWS-managed `/managed/AWSManaged*` roles, so the account can still be administered.

## What it denies

| Statement | Effect |
| --- | --- |
| `DenyOutsideUsEast2` | Everything outside us-east-2, except global services (IAM, STS, Budgets, billing, SSO, Route 53 and similar). Route 53 calls are evaluated as us-east-1, hence the exemption. |
| `DenyServicesCommitmentTrackerDoesNotUse` | Every service not on the allow-list. The list has FlakeHunter's services plus `transcribe:*`, `events:*` (the Transcribe completion rule) and `polly:*` (the sample clips). |
| `DenyLargeEc2Instances` | `RunInstances` for anything but a `t3` or `t4g` instance of size nano to medium, or a `t3a.xlarge` (4 vCPU, 16 GiB). EC2 itself is on the allow-list (`ec2:*`). |
| `DenyLargeEc2Volumes` | EBS volumes over 30 GiB, whether created alone or with an instance. This is the "small local storage" cap. |
| `DenyMultiRegionAndEdgeFeatures` | Lambda@Edge replication, StackSets, DynamoDB global tables, S3 replication and multi-Region KMS keys. |
| `DenyLongLivedIamCredentials` | IAM users, access keys and login profiles. Access is through SSO only. |
| `ProtectBudgetKillSwitch` | Changes to the budget, the stop function and its topic, except by CDK's CloudFormation execution role. |

**When the stacks gain a service, add it to the allow-list first.** Otherwise the deploy fails with an explicit
deny in the CloudFormation execution role.

The kill-switch ARNs assume the API stack is named `CommitmentTrackerApi`, with logical ids `BudgetStopFunction`
and `BudgetStopTopic`. The infra tests will check that the stack matches these names once the stack exists.

`polly:*` is needed only while `make_samples.py` and the latency test run. Remove it from the allow-list afterwards
and update the policy.

## Attach it

Set the project account's id in the shell first; account ids are not stored in this repository. The commands use
a `g26work2-mgmt` profile for the management account and a `g26work2` profile for the new account.

```bash
export CT_ACCOUNT_ID=<commitment-tracker-account-id>
```

Check the policy (no findings expected):

```bash
aws accessanalyzer validate-policy --policy-type SERVICE_CONTROL_POLICY --policy-document file://infra/scp/commitment-tracker-guardrails.json --profile g26work2-mgmt
```

An account, OU or root can have at most five SCPs attached, AWS-managed ones included. Check what is attached
already:

```bash
aws organizations list-policies-for-target --target-id "$CT_ACCOUNT_ID" --filter SERVICE_CONTROL_POLICY --profile g26work2-mgmt
```

Create the policy, and note the `Id` it prints:

```bash
aws organizations create-policy --type SERVICE_CONTROL_POLICY --name commitment-tracker-guardrails --description "Region lock, service allow-list and kill-switch protection for Commitment Tracker AI" --content file://infra/scp/commitment-tracker-guardrails.json --profile g26work2-mgmt
```

Attach it to the project account:

```bash
aws organizations attach-policy --policy-id <policy-id> --target-id "$CT_ACCOUNT_ID" --profile g26work2-mgmt
```

After editing the file, update the attached policy in place:

```bash
aws organizations update-policy --policy-id <policy-id> --content file://infra/scp/commitment-tracker-guardrails.json --profile g26work2-mgmt
```

Changes take effect within a few minutes.

## Check it works

From the project account's profile, a call in another Region and a call to a service off the list should both
fail with an explicit deny in a service control policy:

```bash
aws sqs list-queues --region us-east-2 --profile g26work2
```

```bash
aws transcribe list-transcription-jobs --region us-west-2 --profile g26work2
```

The same Transcribe call in us-east-2 should succeed.
