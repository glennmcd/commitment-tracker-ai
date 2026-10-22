# 0007. A separate AWS account for the demo

Date: 2026-10-21 · Status: Accepted

## Context

FlakeHunter runs in the g26work member account under a guardrail service control policy (SCP) that allows a
fixed list of services. Transcribe, Polly and EventBridge are not on it. That account's budget covers the whole
account, and its kill switch stops FlakeHunter's API. The `g26work.com` hosted zone also lives there. This demo is
public and invites visitors to probe it, so its spend and failures should not reach FlakeHunter.

## Decision

Deploy Part 2 into a new member account of the organization, in us-east-2. The owner does the setup outside CDK,
following `docs/deploying.md`:

1. **Account and access.** Create the account, an SSO permission set and a CLI profile.
2. **Guardrails.** Attach `infra/scp/commitment-tracker-guardrails.json` from the management account. It is
   adapted from FlakeHunter's, with this project's service allow-list.
3. **CDK.** Bootstrap CDK in us-east-2.
4. **DNS.** Create a hosted zone for `commitmentai.g26work.com` in the new account and delegate it with NS records
   in the `g26work.com` zone.
5. **API key.** Store the Anthropic API key as an SSM SecureString parameter.

## Consequences

- **Budget.** The account budget covers only this project, so FlakeHunter's budget kill switch carries over
  unchanged: $30 a month, stopping both Lambda functions at 100% actual spend. The API's $5 daily cap sits in front
  of it.
- **Isolation.** Quotas, concurrency and the blast radius of a mistake are this project's own.
- **Amplify.** Amplify writes its certificate and domain records into the delegated zone without cross-account
  access.
- **Owner setup.** More one-time setup than sharing the g26work account, all of it the owner's to run.
- **Latency test.** The test waits for the account (ADR 0002).

## Alternatives considered

- **The g26work account with per-project budgets** filtered on the `project` tag. Less setup, but it needs the
  tag activated for cost allocation and a widened FlakeHunter SCP, and it shares quotas.
- **The g26work account with one account-wide budget.** Either app's spend could stop both.
