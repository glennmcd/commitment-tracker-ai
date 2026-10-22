import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Match } from "aws-cdk-lib/assertions";
import { DEFAULT_ORIGINS } from "../lib/api-stack.js";
import { BUILD_SPEC, CUSTOM_HEADERS } from "../lib/web-stack.js";
import { synthAll } from "./synth.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const { webDefaults, webWithApi, webConnected, webDomain, webBranch, ...others } = synthAll();

type Json = Record<string, unknown>;

function appProperties(template: typeof webDefaults.template): Json {
  const [app] = Object.values(template.findResources("AWS::Amplify::App"));
  if (!app) throw new Error("no Amplify app");
  return app.Properties as Json;
}

describe("the Amplify app", () => {
  it("is a static site: platform WEB, built from frontend into out", () => {
    const props = appProperties(webDefaults.template);
    expect(props).toMatchObject({ Name: "commitment-tracker-web", Platform: "WEB" });
    expect(props.BuildSpec).toBe(BUILD_SPEC);
    expect(BUILD_SPEC).toContain("appRoot: frontend");
    expect(BUILD_SPEC).toContain("baseDirectory: out");
    expect(BUILD_SPEC).toContain("bun install --frozen-lockfile");
    expect(BUILD_SPEC).toContain("bun run build");
  });

  it("has no server-side parts: no service role, no secrets, no stack parameters", () => {
    expect(appProperties(webDefaults.template)).not.toHaveProperty("IAMServiceRole");
    expect(Object.keys(webDefaults.template.toJSON().Parameters ?? {})).toEqual(["BootstrapVersion"]);
    expect(webDefaults.template.findResources("AWS::IAM::Role")).toEqual({});
  });

  it("builds the API's address into the bundle", () => {
    expect(appProperties(webDefaults.template).EnvironmentVariables).toEqual([
      { Name: "AMPLIFY_MONOREPO_APP_ROOT", Value: "frontend" },
      { Name: "NEXT_TELEMETRY_DISABLED", Value: "1" },
      { Name: "NEXT_PUBLIC_API_BASE_URL", Value: "https://api.example.com" },
    ]);
  });

  it("takes the API's address from the API stack, which is only a token when the app is built", () => {
    expect(webWithApi.error).toBeUndefined();
    const value = (appProperties(webWithApi.template).EnvironmentVariables as { Name: string; Value: unknown }[]).find(
      (v) => v.Name === "NEXT_PUBLIC_API_BASE_URL",
    )?.Value;
    expect(JSON.stringify(value)).toContain("Fn::ImportValue");
  });

  it("sends security headers, and lets only the site use the microphone", () => {
    expect(appProperties(webDefaults.template).CustomHeaders).toBe(CUSTOM_HEADERS);
    expect(CUSTOM_HEADERS).toContain("nosniff");
    expect(CUSTOM_HEADERS).toContain("X-Frame-Options");
    expect(CUSTOM_HEADERS).toContain("microphone=(self), camera=(), geolocation=()");
  });
});

describe("the branch", () => {
  it("is the production branch, built by hand until a repository is connected", () => {
    webDefaults.template.hasResourceProperties("AWS::Amplify::Branch", {
      BranchName: "main",
      Stage: "PRODUCTION",
      EnableAutoBuild: false,
    });
    expect(webDefaults.warnings.some((w) => w.includes("not connected to GitHub"))).toBe(true);
  });

  it("builds on every push once connected, with the token read from Secrets Manager at deploy time", () => {
    webConnected.template.hasResourceProperties("AWS::Amplify::Branch", { EnableAutoBuild: true });
    const props = appProperties(webConnected.template);
    expect(props.Repository).toBe("https://github.com/glennmcd/commitment-tracker-ai");
    expect(String(props.AccessToken)).toContain("{{resolve:secretsmanager:commitment-tracker/github-token");
    expect(webConnected.warnings.filter((w) => w.includes("not connected"))).toEqual([]);
  });

  it("follows the branch prop", () => {
    webBranch.template.hasResourceProperties("AWS::Amplify::Branch", { BranchName: "release" });
  });
});

describe("the custom domain", () => {
  it("is not created unless asked for", () => {
    expect(webDefaults.template.findResources("AWS::Amplify::Domain")).toEqual({});
  });

  it("serves each prefix from the branch, after the branch exists", () => {
    webDomain.template.hasResourceProperties("AWS::Amplify::Domain", {
      DomainName: "example.com",
      EnableAutoSubDomain: false,
      SubDomainSettings: [
        { Prefix: "", BranchName: "main" },
        { Prefix: "www", BranchName: "main" },
        { Prefix: "app.dev", BranchName: "main" },
      ],
    });
    const [domain] = Object.values(webDomain.template.findResources("AWS::Amplify::Domain"));
    expect(JSON.stringify(domain?.DependsOn)).toContain("Branch");
  });

  it("names the site as its output", () => {
    const outputs = (name: typeof webDomain) => name.template.toJSON().Outputs as Record<string, { Value: unknown }>;
    expect(outputs(webDomain).SiteUrl?.Value).toBe("https://example.com");
    expect(JSON.stringify(outputs(webDefaults).SiteUrl?.Value)).toContain("DefaultDomain");
    webDomain.template.hasOutput("AmplifyAppId", Match.anyValue());
  });
});

describe("bad web props", () => {
  it.each([
    ["badDomainName", "customDomain.domainName must be a lowercase domain"],
    ["badDomainNoSubDomains", "customDomain.subDomains must list at least one prefix"],
    ["badDomainPrefix", "customDomain.subDomains has an invalid prefix"],
    ["badDomainDuplicate", "customDomain.subDomains lists a prefix twice"],
    ["badRepository", "repository must look like https://github.com/<owner>/<repo>"],
    ["badBranch", "branch must be a plain branch name"],
    ["badApiUrl", "apiUrl must be an https origin"],
  ] as const)("%s is refused", (name, message) => {
    expect(others[name].error).toContain(message);
  });
});

describe("the contract with the API stack and the app", () => {
  it("serves the site from a domain that the API's CORS and the bucket accept", () => {
    const cdk = JSON.parse(readFileSync(path.join(here, "../cdk.json"), "utf8")) as {
      context: { customDomain: { domainName: string; subDomains: string[] } };
    };
    const { domainName, subDomains } = cdk.context.customDomain;
    expect(domainName).toBe("commitmentai.g26work.com");
    expect(subDomains).toEqual([""]);
    expect((DEFAULT_ORIGINS as readonly string[]).includes(`https://${domainName}`)).toBe(true);
  });

  it("is added to the app after the API, which supplies its URL", () => {
    const app = readFileSync(path.join(here, "../bin/commitment-tracker.ts"), "utf8");
    expect(app).toContain('new WebStack(app, "CommitmentTrackerWeb"');
    expect(app).toContain("apiUrl: api.httpApiUrl");
  });
});
