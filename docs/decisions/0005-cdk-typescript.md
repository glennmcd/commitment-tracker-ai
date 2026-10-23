# 0005. AWS CDK in TypeScript for the infrastructure

Date: 2026-10-21 · Status: Accepted

## Context

Part 2 deploys an HTTP API on Lambda, an S3 bucket, three DynamoDB tables, an EventBridge rule, SSM parameters, a
budget kill switch, alarms and an Amplify site. FlakeHunter already has CDK constructs for most of these, with tests
that synthesize without AWS credentials: the API stack, the scoped SSM read, the rate limit table, the budget kill
switch and the Amplify web stack with a custom domain. The frontend brings TypeScript into the repo anyway.

## Decision

- **Language and layout.** AWS CDK in TypeScript under `infra/`, adapted from FlakeHunter's stacks and test
  harness. Bun installs packages and runs the tests; Node runs `cdk synth`.
- **Linting.** Biome, from one root `biome.json` shared with `frontend/`.
- **IAM tests.** Every role's policy is asserted statement by statement, so a widened permission fails CI.
- **Credentials.** Stacks synthesize with no credentials, so CI checks them.
- **Deploying.** The agent synthesizes and tests; the owner runs `cdk deploy`.

## Consequences

- **Languages.** The repo has two: Python for the backend, TypeScript for the frontend and infra.
- **Copied code.** FlakeHunter's constructs are copied and adapted, not shared as a package. A fix in one project
  has to be ported to the other by hand.
- **CI.** CI gains an infra job: `bun test` and `cdk synth`.

## Alternatives considered

- **CDK in Python.** One language for the backend and the infra, but every FlakeHunter construct and test would
  have to be rewritten.
- **Terraform or SAM.** Neither reuses the existing constructs or their tests.
