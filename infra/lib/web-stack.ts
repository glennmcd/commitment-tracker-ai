import { Annotations, CfnOutput, SecretValue, Stack, type StackProps, Tags, Token } from "aws-cdk-lib";
import { CfnApp, CfnBranch, CfnDomain } from "aws-cdk-lib/aws-amplify";
import type { Construct } from "constructs";

/**
 * A custom domain served by the branch. Amplify issues and renews the certificate and, when the domain's Route 53
 * hosted zone is in this account, writes the DNS records itself; with the zone elsewhere it times out waiting for them.
 * The project's zone for commitmentai.g26work.com is delegated into this account (docs/decisions/0007).
 */
export interface CustomDomain {
  /** The domain, for example commitmentai.g26work.com. */
  domainName: string;
  /** Prefixes to serve: "" is the domain itself, "www" serves www.<domainName>. */
  subDomains: string[];
}

const DOMAIN_NAME = /^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
const SUBDOMAIN_PREFIX = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$/;
const GITHUB_REPOSITORY = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

function checkCustomDomain({ domainName, subDomains }: CustomDomain): void {
  if (!DOMAIN_NAME.test(domainName)) {
    throw new Error(`customDomain.domainName must be a lowercase domain such as example.com: got "${domainName}"`);
  }
  if (!Array.isArray(subDomains) || subDomains.length === 0) {
    throw new Error('customDomain.subDomains must list at least one prefix ("" for the domain itself)');
  }
  for (const prefix of subDomains) {
    if (prefix !== "" && !SUBDOMAIN_PREFIX.test(prefix)) {
      throw new Error(`customDomain.subDomains has an invalid prefix: "${prefix}"`);
    }
  }
  if (new Set(subDomains).size !== subDomains.length) {
    throw new Error("customDomain.subDomains lists a prefix twice");
  }
}

export interface WebStackProps extends StackProps {
  /** The API's base URL (the HTTP API endpoint); built into the site as NEXT_PUBLIC_API_BASE_URL. */
  apiUrl: string;
  /** HTTPS URL of the GitHub repository to build from, for example https://github.com/glennmcd/commitment-tracker-ai. */
  repository?: string;
  /**
   * Name of an AWS Secrets Manager secret holding a GitHub personal access token Amplify uses to read the repository
   * and register its webhook. Resolved by CloudFormation at deploy time, so the token is never in the template.
   * Without it (or without `repository`) the app is created unconnected and the repository is attached in the console.
   */
  githubTokenSecretName?: string;
  /** Branch to build and serve. */
  branch?: string;
  /**
   * Serve the branch on a custom domain as well. Removing it from a later deploy deletes the domain association, so
   * keep it in cdk.json rather than passing it per deploy.
   */
  customDomain?: CustomDomain;
}

/**
 * The monorepo build for Amplify Hosting's static platform (`WEB`): the site is a Next.js static export, so the build
 * writes plain files to `frontend/out` and no server runs. Notes:
 * - `appRoot` points Amplify at frontend; the install runs at the repo root so the workspace resolves.
 * - Amplify's build image has no Bun, so it is installed with npm at the version CI uses.
 * - `NEXT_PUBLIC_API_BASE_URL` is an Amplify environment variable; Next reads it at build time and writes it into the
 *   bundle. There are no secrets in this app.
 */
export const BUILD_SPEC = `version: 1
applications:
  - appRoot: frontend
    frontend:
      phases:
        preBuild:
          commands:
            - nvm use 22 || nvm install 22
            - npm install --global bun@1.4.2
            - cd ..
            - bun install --frozen-lockfile
            - cd frontend
        build:
          commands:
            - bun run build
      artifacts:
        baseDirectory: out
        files:
          - '**/*'
      cache:
        paths:
          - ../node_modules/**/*
`;

/**
 * Response headers for every path. The microphone is allowed for the site itself (the recorder) and the camera and
 * location are not. A content security policy waits until the frontend's inline scripts are known.
 * Like the build spec, a monorepo's headers must sit under `applications` with the app root, or Amplify refuses them
 * ("Monorepo spec provided without applications key").
 */
export const CUSTOM_HEADERS = `applications:
  - appRoot: frontend
    customHeaders:
      - pattern: '**'
        headers:
          - key: X-Content-Type-Options
            value: nosniff
          - key: X-Frame-Options
            value: DENY
          - key: Referrer-Policy
            value: strict-origin-when-cross-origin
          - key: Permissions-Policy
            value: microphone=(self), camera=(), geolocation=()
`;

export class WebStack extends Stack {
  readonly app: CfnApp;

  constructor(scope: Construct, id: string, props: WebStackProps) {
    super(scope, id, props);

    const branchName = props.branch ?? "main";
    if (!/^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$/.test(branchName)) {
      throw new Error(`branch must be a plain branch name: got "${branchName}"`);
    }
    if (props.repository && !GITHUB_REPOSITORY.test(props.repository)) {
      throw new Error(`repository must look like https://github.com/<owner>/<repo>: got "${props.repository}"`);
    }
    // The address of the API stack is a token until deploy time, so only a literal one can be checked.
    if (!Token.isUnresolved(props.apiUrl) && !/^https:\/\/[^/\s]+$/.test(props.apiUrl)) {
      throw new Error(`apiUrl must be an https origin: got "${props.apiUrl}"`);
    }
    if (props.customDomain) checkCustomDomain(props.customDomain);
    Tags.of(this).add("project", "commitment-tracker");

    const connected = Boolean(props.repository && props.githubTokenSecretName);
    this.app = new CfnApp(this, "WebApp", {
      name: "commitment-tracker-web",
      // A static export needs no server: WEB, not WEB_COMPUTE, so Amplify serves the files in `out` as they are.
      platform: "WEB",
      buildSpec: BUILD_SPEC,
      customHeaders: CUSTOM_HEADERS,
      ...(connected
        ? {
            repository: props.repository,
            // A CloudFormation dynamic reference to Secrets Manager, resolved at deploy time.
            accessToken: SecretValue.secretsManager(props.githubTokenSecretName as string).unsafeUnwrap(),
          }
        : {}),
      environmentVariables: [
        { name: "AMPLIFY_MONOREPO_APP_ROOT", value: "frontend" },
        { name: "NEXT_TELEMETRY_DISABLED", value: "1" },
        { name: "NEXT_PUBLIC_API_BASE_URL", value: props.apiUrl },
      ],
    });

    const branch = new CfnBranch(this, "Branch", {
      appId: this.app.attrAppId,
      branchName,
      stage: "PRODUCTION",
      enableAutoBuild: connected,
    });

    if (props.customDomain) {
      // Without a certificate setting Amplify manages the certificate.
      const domain = new CfnDomain(this, "Domain", {
        appId: this.app.attrAppId,
        domainName: props.customDomain.domainName,
        enableAutoSubDomain: false,
        subDomainSettings: props.customDomain.subDomains.map((prefix) => ({ prefix, branchName })),
      });
      // The branch name is a plain string, so CloudFormation would not otherwise wait for the branch to exist.
      domain.addResourceDependency(branch);
    }

    if (!connected) {
      Annotations.of(this).addWarningV2(
        "commitment-tracker:web-not-connected",
        "No repository and githubTokenSecretName given, so the Amplify app is not connected to GitHub. Pass " +
          "-c repository=https://github.com/<owner>/<repo> -c githubTokenSecretName=<secret> or connect it in the console.",
      );
    }

    new CfnOutput(this, "AmplifyAppId", { value: this.app.attrAppId });
    new CfnOutput(this, "SiteUrl", {
      value: props.customDomain
        ? `https://${props.customDomain.subDomains[0] ? `${props.customDomain.subDomains[0]}.` : ""}${props.customDomain.domainName}`
        : `https://${branchName}.${this.app.attrDefaultDomain}`,
      description: "The site",
    });
  }
}
