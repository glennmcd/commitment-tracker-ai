import { readFileSync } from "node:fs";
import type { NextConfig } from "next";
import { versionFromManifest } from "./src/lib/releaseVersion";

// The footer's version comes from release-please's manifest at the repository root, so it is never kept by hand.
function releaseVersion(): string | undefined {
  try {
    return versionFromManifest(readFileSync(new URL("../.release-please-manifest.json", import.meta.url), "utf8"));
  } catch {
    return undefined;
  }
}

// A static export (ADR: docs/plans/part-2-audio-and-deploy.md, "Frontend"): `next build` writes plain files to `out/`,
// which Amplify Hosting serves. The site has no server code, no secrets and no request-time rendering, so it uses none
// of what a static export leaves out (cookies, rewrites, Server Actions, request-dependent route handlers).
const version = releaseVersion();

const config: NextConfig = {
  output: "export",
  // Every route is written as <route>/index.html, which any static host (and e2e/serve.mjs) serves for <route>/.
  trailingSlash: true,
  // The export has no image optimizer to call.
  images: { unoptimized: true },
  reactStrictMode: true,
  // Written into the bundle at build time, like NEXT_PUBLIC_API_BASE_URL. Not set when the manifest is unreadable.
  env: version ? { NEXT_PUBLIC_APP_VERSION: version } : {},
};

export default config;
