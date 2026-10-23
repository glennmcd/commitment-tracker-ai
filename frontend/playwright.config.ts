import { defineConfig, devices } from "@playwright/test";

// The site is a static export, so the test serves out/ and mocks the API with page.route (see e2e/run.mjs for the build).
export default defineConfig({
  testDir: "e2e",
  testMatch: "*.spec.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://localhost:4173", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: { command: "node e2e/serve.mjs", url: "http://localhost:4173", reuseExistingServer: !process.env.CI },
});
