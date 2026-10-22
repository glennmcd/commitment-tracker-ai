import type { NextConfig } from "next";

// A static export (ADR: docs/plans/part-2-audio-and-deploy.md, "Frontend"): `next build` writes plain files to `out/`,
// which Amplify Hosting serves. The site has no server code, no secrets and no request-time rendering, so it uses none
// of what a static export leaves out (cookies, rewrites, Server Actions, request-dependent route handlers).
const config: NextConfig = {
  output: "export",
  // The export has no image optimizer to call.
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default config;
