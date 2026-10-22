import { expect, type Page, type Route, test } from "@playwright/test";

const API = "http://api.test";
const JOB_ID = "a".repeat(64);

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "content-type",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  // As on the real API (infra/lib/api-stack.ts): without this the page cannot read Retry-After across origins.
  "access-control-expose-headers": "retry-after",
};

const finished = {
  job_id: JOB_ID,
  status: "done",
  error_code: null,
  latency_ms: { upload_ms: null, transcribe_ms: null, analyze_ms: 1400, total_ms: 1700 },
  transcript: [
    { speaker: "Ana", text: "Can you get me the numbers?" },
    { speaker: "Ben", text: "I'll try to get them over to you sometime this week, no promises." },
  ],
  analysis: {
    metadata: {},
    spans: [
      {
        turn_index: 0,
        label: "REQUEST",
        owner: null,
        recipient: "Ben",
        action: "send the numbers",
        due: { raw: null, resolved: null, precision: "none" },
        condition: null,
        confidence: 0.9,
        quote: "Can you get me the numbers?",
        rationale: "Ana asks Ben to act.",
        ambiguous: false,
        in_ledger: false,
        soft: false,
      },
      {
        turn_index: 1,
        label: "HEDGED",
        owner: "Ben",
        recipient: "Ana",
        action: "send the numbers",
        due: { raw: "sometime this week", resolved: "2026-10-19", precision: "week" },
        condition: null,
        confidence: 0.82,
        quote: "I'll try to get them over to you sometime this week",
        rationale: "Names an action but softens it with try and no promises.",
        ambiguous: false,
        in_ledger: true,
        soft: true,
      },
    ],
  },
};

/** Answers the API's calls from the page, preflights included, and records what the page sent. */
async function mockApi(page: Page) {
  const sent: { method: string; path: string; body: unknown }[] = [];
  await page.route(`${API}/**`, async (route: Route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const path = new URL(request.url()).pathname;
    sent.push({ method: request.method(), path, body: request.postDataJSON() });
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });
    if (path === "/jobs" && request.method() === "POST") return json(202, { ...finished, status: "uploaded" });
    if (path === `/jobs/${JOB_ID}`) return json(200, finished);
    if (path === "/feedback") return json(200, { transcript_kept: false });
    return json(404, { error: { code: "job_not_found", message: "m", details: [] } });
  });
  return sent;
}

test("text mode: a prompt chip, the results, and a vote", async ({ page }) => {
  const sent = await mockApi(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Commitment Tracker AI" })).toBeVisible();
  await page.getByRole("button", { name: "Try a hedge" }).click();
  await expect(page.getByLabel("Conversation")).toHaveValue(/no promises/);

  await page.getByRole("button", { name: "Find commitments" }).click();

  // A hedged commitment is in the ledger, marked soft in words; the request is a near miss.
  const ledger = page.getByRole("region", { name: "Commitments" });
  await expect(ledger.getByText("Hedged")).toBeVisible();
  await expect(ledger.getByText("· soft")).toBeVisible();
  await expect(ledger.getByText("sometime this week (2026-10-19)")).toBeVisible();
  const misses = page.getByRole("region", { name: "Not a commitment" });
  await expect(misses.getByText("Request")).toBeVisible();
  await expect(page.getByRole("region", { name: "Transcript" }).locator("mark")).toHaveCount(2);

  const job = sent.find((call) => call.path === "/jobs");
  expect(job?.body).toMatchObject({
    transcript: [{ speaker: "Ana" }, { speaker: "Ben" }],
    call_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
  });

  await ledger.getByRole("button", { name: /Right/ }).click();
  await expect(ledger.getByText("Thanks, that is noted.")).toBeVisible();
  expect(sent.find((call) => call.path === "/feedback")?.body).toEqual({
    job_id: JOB_ID,
    span_index: 1,
    vote: "up",
    consent: false,
  });
});

test("an API refusal is shown as a sentence, and the form stays usable", async ({ page }) => {
  await page.route(`${API}/**`, async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    return route.fulfill({
      status: 429,
      headers: { ...CORS, "content-type": "application/json", "retry-after": "30" },
      body: JSON.stringify({ error: { code: "rate_limited", message: "m", details: [] } }),
    });
  });
  await page.goto("/");

  await page.getByLabel("Conversation").fill("Ana: Hello.\nBen: Hi.");
  await page.getByRole("button", { name: "Find commitments" }).click();

  // Next also has an empty alert region for route changes, so pick ours by its text.
  await expect(page.getByRole("alert").filter({ hasText: "Too many requests" })).toContainText(
    "Try again in 30 seconds.",
  );
  await expect(page.getByRole("button", { name: "Find commitments" })).toBeEnabled();
});

test("the page works by keyboard alone and has no horizontal scroll on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);

  await page.keyboard.press("Tab");
  await expect(page.getByRole("radio", { name: "Type or paste" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Record" })).toBeChecked();
  await expect(page.getByText(/sent to be turned into text and analysed, then deleted/)).toBeVisible();
});
