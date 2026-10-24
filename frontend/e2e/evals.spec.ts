import { expect, test } from "@playwright/test";
import index from "../src/data/evals/index.json" with { type: "json" };

// The evaluation pages are static and sit outside the password gate: no API, no password.
test("opens a run, then its items, without the password", async ({ page }) => {
  const run = index.runs[0];
  if (!run) throw new Error("the export has no runs");

  await page.goto("/evals/");
  await expect(page.getByRole("heading", { level: 1, name: "Evaluation" })).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveCount(0);

  await page.locator(`a[href="/evals/runs/${run.run}/"]`).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(run.configuration);
  await expect(page.getByRole("table", { name: /confusion matrix/i })).toBeVisible();

  await page.getByRole("link", { name: "See every item" }).click();
  await expect(page.getByRole("status")).toContainText(`of ${run.items} items`);
  const first = page.getByRole("article").first();
  await expect(first).toBeVisible();
  await expect(first.getByRole("heading", { level: 3 })).not.toBeEmpty();
});

test("the home page links to the evaluation", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /evaluation results/i }).click();
  await expect(page).toHaveURL(/\/evals\/$/);
});
