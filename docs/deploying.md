# Deploying

How to put the demo live at `commitmentai.g26work.com`. You run every command here: the agent synthesizes and tests
the stacks but never deploys, creates AWS resources or attaches the SCP. The design is in
[the Part 2 plan](plans/part-2-audio-and-deploy.md), and the reasons for the separate account are in
[ADR 0007](decisions/0007-separate-aws-account.md).

Two CDK stacks, in `us-east-2`:

| Stack | Holds |
| --- | --- |
| `CommitmentTrackerApi` | The audio bucket, three DynamoDB tables, the API and worker Lambda functions, the HTTP API, the Transcribe completion rule, the budget kill switch and the alarms |
| `CommitmentTrackerWeb` | The Amplify Hosting app (a static Next.js export) and the custom domain |

You need Bun 1.4.2, Node 22, uv with Python 3.12, and the AWS CLI v2. Commands use the profile `g26work2` for the
project account and `g26work2-mgmt` for the management account. Use your own names if they differ.

## One-time setup

1. **Create the account.** Create a member account in the organization for this project, give yourself an SSO
   permission set on it, add the `g26work2` CLI profile and turn on budget alerts. Then sign in:

   ```bash
   aws sso login --profile g26work2
   ```

2. **Attach the guardrail SCP** from the management account, and check it with the commands in
   [infra/scp/README.md](../infra/scp/README.md). Do this before the first deploy: it locks the account to
   `us-east-2` and to the services the stacks use. If you add a service to a stack, add it to the SCP's allow-list
   first, or the deploy fails with an explicit deny.

3. **Bootstrap CDK** in the account. Use the account id from `aws sts get-caller-identity --profile g26work2`:

   ```bash
   cd infra && bun run cdk bootstrap aws://<account-id>/us-east-2 --profile g26work2
   ```

4. **Delegate DNS.** Create a hosted zone for `commitmentai.g26work.com` in the project account:

   ```bash
   aws route53 create-hosted-zone --name commitmentai.g26work.com --caller-reference ct-$(date +%s) --profile g26work2
   ```

   Add the zone's four NS records to the `g26work.com` zone in the g26work account, as one NS record set named
   `commitmentai`. Amplify then writes its certificate validation and site records into the delegated zone itself.

5. **Store the Anthropic key** as a SecureString parameter. The Lambda functions read it at cold start, and it never
   goes in the environment, the template or a log. The command prompts for nothing, so paste the key into the shell
   from a password manager rather than typing it into history:

   ```bash
   aws ssm put-parameter --name /commitment-tracker/prod/ANTHROPIC_API_KEY --type SecureString --value "$ANTHROPIC_API_KEY" --profile g26work2
   ```

   In Git Bash on Windows, put `MSYS_NO_PATHCONV=1` in front of the command. Otherwise Git Bash rewrites the leading
   `/` into a Windows path and SSM answers "Parameter name must be a fully qualified name". PowerShell and WSL need
   nothing. In PowerShell, set the variable with `$env:ANTHROPIC_API_KEY = "..."` and use `$env:ANTHROPIC_API_KEY` in
   place of `"$ANTHROPIC_API_KEY"`.

6. **Set a spend limit in the Anthropic console.** The app's daily cap sees only its own estimate of the model's
   cost, and the AWS budget never sees Anthropic charges, so this is the one limit that applies to the key itself.

7. **Give Amplify a GitHub token** if you want it to build from the repository on every push. Create a
   fine-grained token with read access to the repository and webhook permission, and store it in Secrets Manager.
   CloudFormation reads it at deploy time, so it is never in the template:

   ```bash
   aws secretsmanager create-secret --name commitment-tracker/github-token --secret-string "$GITHUB_TOKEN" --profile g26work2
   ```

   Without it the app is created unconnected, and you connect the repository in the Amplify console.

8. **Set the site password.** Every API endpoint except `GET /health` needs it, and the page asks for it before it
   shows the demo. A Lambda authorizer on the HTTP API compares the `Authorization` header with this SecureString
   parameter. It never goes in the template, the bundle or a log. Create it before the first deploy, because until
   it exists the authorizer refuses every request. Choose a long passphrase and paste it the way step 5 describes
   (and with the same `MSYS_NO_PATHCONV=1` note for Git Bash). Use plain Latin-1 characters, since the header
   cannot carry others:

   ```bash
   aws ssm put-parameter --name /commitment-tracker/prod/SITE_PASSWORD --type SecureString --value "$SITE_PASSWORD" --profile g26work2
   ```

   To change it, add `--overwrite`. API Gateway caches each answer for five minutes, so the old password keeps
   working for up to that long. The password protects the API, and with it the model spend. The page itself and the
   sample clips under `frontend/public/samples/` stay public.

   To give several people their own password, put one per line in the parameter (no blank-line or newline inside a
   password); any of them is accepted. Rather than hand-building that value, keep the passwords in a file, one per
   line (`#` comments and blank lines are ignored; `passwords.txt` is git-ignored), and upload it. Add `--dry-run` to
   check the file without calling AWS:

   ```bash
   bun scripts/upload-passwords.mjs passwords.txt --profile g26work2
   ```

   The values go to the AWS CLI through a private temp file, never the command line or the output. Remove a line and
   upload again to revoke one. A link can carry its password
   as `https://<site>/?password=<value>`: the page tries it, then removes it from the address bar. Anyone holding
   the link has the password, and the query string can land in browser history and server logs, so share such links
   privately.

   Add `&pwsource=<label>` (letters, digits, `.`, `_`, `-`, up to 64) to tell links apart, for example
   `/?password=<value>&pwsource=alice`. The page keeps the label for the tab and sends it as an `X-Source` header; the
   API logs `request method=… path=… pwsource=<label>` (`pwsource=invalid` for a label that doesn't fit) to its
   CloudWatch log group. Only the label is logged, never the password or the `Authorization` header.

## Make the sample clips

The clips are synthesized once with Amazon Polly, and the WAVs are committed. `polly:*` is already on the SCP's
allow-list; remove it afterwards if you like. Check the cost first (about $0.007):

```bash
cd backend && uv run python scripts/make_samples.py --dry-run
```

Then make them:

```bash
cd backend && uv run python scripts/make_samples.py --profile g26work2
```

This writes the WAVs to `frontend/public/samples/`, the manifest the API bundles to
`backend/src/commitment_tracker/jobs/samples.json`, and the timed ground truth to
`backend/samples/ground-truth.jsonl`. Commit all three. Until the clips exist, `cdk synth` warns that none will be
deployed and the picker says none are available.

## Deploy the API

From `infra/`. The `build` step in `cdk.json` runs first: it builds the Lambda bundle with uv (the locked runtime
dependencies as arm64 wheels, about 55 MB unzipped), so it needs network access.

```bash
cd infra && bun run cdk deploy CommitmentTrackerApi -c alertEmail=you@example.com --profile g26work2
```

| Context | Default | Meaning |
| --- | --- | --- |
| `alertEmail` | none | Receives the budget alerts and the alarms. **Without it no budget, kill switch or alarm is created** |
| `dailyBudgetUsd` | 5 | The daily spend cap the API enforces itself |
| `monthlyBudgetUsd` | 30 | The AWS budget that stops both functions at 100% actual spend |
| `model` | `claude-haiku-5-5` | The Anthropic model the deployed functions use. The backend's own default stays `claude-opus-5-5` |
| `throttleRate`, `throttleBurst` | 10, 2×rate | Requests per second the HTTP API accepts across all callers |
| `reservedConcurrency` | none | Caps the API function. A new account's default quota usually can't afford a reservation; check `aws lambda get-account-settings` first |

Confirm the email subscription when AWS sends the message, or no alert arrives. The stack prints these outputs:
`ApiUrl`, `AudioBucketName`, `EvalAudioBucketName`, `ApiFunctionName`, `WorkerFunctionName` and `ApiKeyParameter`.
`EvalAudioBucketName` is the private, versioned bucket of evaluation clips; set it as `EVAL_AUDIO_BUCKET` in
`backend/.env` for `uv run eval-audio` ([evaluation.md](evaluation.md#audio)).

## Deploy the site

```bash
cd infra && bun run cdk deploy CommitmentTrackerWeb -c repository=https://github.com/glennmcd/commitment-tracker-ai -c githubTokenSecretName=commitment-tracker/github-token --profile g26work2
```

The site is a static export, so the Amplify app uses the `WEB` platform and publishes `frontend/out`. The API's
address is built in at build time from the API stack's output. The first deploy confirms that Amplify did not switch
the app to its server-rendering platform: in the console, the app's platform should read "Web". The custom domain
association comes from `cdk.json`. It stays in that file so every deploy carries it, because a deploy without it
would delete the association.

The API's CORS accepts only `https://commitmentai.g26work.com` and `http://localhost:3000`. Until DNS validation
finishes, the default `*.amplifyapp.com` address loads but its API calls are refused. To try the API from your own
machine meanwhile:

```bash
NEXT_PUBLIC_API_BASE_URL=<ApiUrl> bun run --cwd frontend dev
```

## Check it works

List the sample clips through the deployed API:

```bash
curl <ApiUrl>/samples
```

Then measure latency and prove the audio is deleted. Both need a clip id from that list.

```bash
cd backend && uv run python scripts/measure_latency.py --api-url <ApiUrl> --sample-id <clip-id> --json ../latency.json
```

It runs 20 jobs, which is the API's whole hourly allowance for one address, and prints the p50 and p95 of each stage
against the 10-second target. Put the numbers in the README.

```bash
cd backend && uv run python scripts/check_audio_gone.py --api-url <ApiUrl> --bucket <AudioBucketName> --wav ../frontend/public/samples/<clip-id>.wav --profile g26work2
```

It uploads the clip, waits for the job and checks that the upload, Transcribe's output and the Transcribe job are all
gone. It exits 1 if any is still there.

## Spending limits

Three limits stand between a visitor and your bill, from the tightest:

1. **Rate limits**, per client address: 20 uploads and 20 jobs an hour, 30 `/analyze` calls an hour, 120 feedback
   votes an hour and 120 job polls a minute. Past a limit the API answers 429 with `Retry-After`.
2. **The daily cap** (`dailyBudgetUsd`, $5). The API adds Transcribe's estimate when an audio job starts and the
   model's cost after each call, and refuses new jobs with 503 `daily_budget_exhausted` until UTC midnight. A job
   costs about $0.025 with audio and about $0.001 as text, so $5 allows about 200 full-length recordings a day.
3. **The monthly AWS budget** (`monthlyBudgetUsd`, $30). At 100% of actual spend it stops both functions. At the
   cap's rate, about six days of maximum use get there. AWS Budgets refreshes up to three times a day, so this is the
   backstop, not the limiter.

The alarms email you on any unhandled worker error, on more than 5% 5xx responses (with at least ten requests in
five minutes), and when the day's spending reaches 80% of the cap.

### When the kill switch has fired

Both functions refuse every invocation until you remove their reserved concurrency. Find the names in the stack
outputs, then for each function:

```bash
aws lambda delete-function-concurrency --function-name <ApiFunctionName> --profile g26work2
```

```bash
aws lambda delete-function-concurrency --function-name <WorkerFunctionName> --profile g26work2
```

Wait for the budget to reset or raise `monthlyBudgetUsd` first, or the next budget refresh stops them again.

### Testing the chain

Publishing to the stop topic trips the switch, so this takes the demo down until you reset it. Find the topic with
`aws sns list-topics --profile g26work2` (its name contains `BudgetStopTopic`), then:

```bash
aws sns publish --topic-arn <topic-arn> --message test --profile g26work2
```

Within a minute `aws lambda get-function-concurrency` on each function should report 0. Reset them as above.

## Updating and tearing down

- **Backend or infra changes:** run `cdk deploy CommitmentTrackerApi` again. The bundle is rebuilt each time.
- **Frontend changes:** push to the connected branch, and Amplify builds it. If you changed the API's shape, run
  `uv run export-openapi` and `bun run --cwd frontend gen:api` first, and commit both. CI fails when they are stale.
- **A different model:** deploy with `-c model=<id>`. A new prompt version is a backend change: set
  `PROMPT_VERSION` in the functions' environment by adding it to the API stack.
- **Tearing down:** `cdk destroy` removes the stacks, but the audio bucket and the feedback table are retained on
  purpose (the table holds the votes). Delete them by hand if you want them gone.

## What it costs

| Item | About |
| --- | --- |
| Transcribe, batch | $0.024 a minute of audio, so $0.024 for a full clip |
| Model call | $0.001 on `claude-haiku-5-5` |
| Polly, once | $0.007 for the four sample clips |
| Lambda, API Gateway, DynamoDB, S3, Amplify | pennies at demo traffic |

The Transcribe rate is the pricing page's example for `us-east-1`; confirm the `us-east-2` rate against your bill.
