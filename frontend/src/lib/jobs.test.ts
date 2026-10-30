import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { type JobResult, pollJob, startTextJob } from "./jobs";
import { fakeClient, ok, failure } from "@/lib/testExports";
const ID = "a".repeat(64);
const latency = { total_ms: null };
const job = (status: string, extra: object = {}) => ({ job_id: ID, status, latency_ms: latency, ...extra });

describe("startTextJob", () => {
  it("posts the turns and call date, and returns the job", async () => {
    const { client, post } = fakeClient([ok(job("uploaded"), 202)]);
    const turns = [{ speaker: "Ana", text: "Hello." }];

    const result = await startTextJob(client, turns, "2026-10-21");

    expect(post).toHaveBeenCalledWith("/jobs", { body: { transcript: turns, call_date: "2026-10-21" } });
    expect(result).toMatchObject({ ok: true, job: { job_id: ID, status: "uploaded" } });
  });

  it.each([
    ["rate_limited", 429, { "retry-after": "30" }, "Too many requests. Try again in 30 seconds."],
    [
      "daily_budget_exhausted",
      503,
      { "retry-after": "3600" },
      "The demo has reached its daily limit. Try again tomorrow.",
    ],
    ["validation_error", 422, {}, "The API did not accept that request."],
    ["jobs_unavailable", 503, {}, "The demo is not available right now."],
  ])("explains %s", async (code, status, headers, message) => {
    const { client } = fakeClient([failure(code, status, headers)]);
    expect(await startTextJob(client, [{ speaker: "A", text: "x" }], "2026-10-21")).toEqual({ ok: false, message });
  });

  it("says so when the API cannot be reached", async () => {
    const client = { POST: vi.fn().mockRejectedValue(new TypeError("fetch failed")) } as unknown as ApiClient;
    expect(await startTextJob(client, [{ speaker: "A", text: "x" }], "2026-10-21")).toEqual({
      ok: false,
      message: "Could not reach the API. Check your connection and try again.",
    });
  });
});

describe("pollJob", () => {
  const noWait = async () => {};

  it("reports each status until the job is done", async () => {
    const done = job("done", { analysis: { spans: [], metadata: {} }, transcript: [] });
    const { client, get } = fakeClient([], [ok(job("transcribing")), ok(job("analyzing")), ok(done)]);
    const seen: string[] = [];

    const result = await pollJob(client, ID, { wait: noWait, onUpdate: (j) => seen.push(j.status) });

    expect(seen).toEqual(["transcribing", "analyzing", "done"]);
    expect(get).toHaveBeenCalledTimes(3);
    expect(get).toHaveBeenCalledWith("/jobs/{job_id}", { params: { path: { job_id: ID } } });
    expect(result).toMatchObject({ ok: true, job: { status: "done" } });
  });

  it("turns a failed job into its explanation", async () => {
    const { client } = fakeClient([], [ok(job("failed", { error_code: "model_unavailable" }))]);
    const result: JobResult = await pollJob(client, ID, { wait: noWait });
    expect(result).toEqual({ ok: false, message: "The model is unavailable right now. Try again in a minute." });
  });

  it("gives up with a message when the job disappears", async () => {
    const { client } = fakeClient([], [failure("job_not_found", 404)]);
    expect(await pollJob(client, ID, { wait: noWait })).toEqual({
      ok: false,
      message: "That job has expired. Run it again.",
    });
  });

  it("stops quietly when cancelled", async () => {
    const controller = new AbortController();
    const { client, get } = fakeClient([], [ok(job("transcribing")), ok(job("done"))]);
    const wait = async () => controller.abort();

    const result = await pollJob(client, ID, { wait, signal: controller.signal });

    expect(result).toEqual({ ok: false, message: "Cancelled.", cancelled: true });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("gives up after the time limit", async () => {
    const { client } = fakeClient(
      [],
      Array.from({ length: 5 }, () => ok(job("analyzing"))),
    );
    const result = await pollJob(client, ID, { wait: noWait, maxPolls: 3 });
    expect(result).toEqual({ ok: false, message: "This is taking longer than expected. Try again." });
  });

  it("retries a failed poll a few times before giving up", async () => {
    const calls = [new TypeError("x"), new TypeError("x"), ok(job("done", { analysis: { spans: [], metadata: {} } }))];
    const get = vi.fn(async () => {
      const next = calls.shift();
      if (next instanceof Error) throw next;
      return next;
    });
    const client = { GET: get } as unknown as ApiClient;

    const result = await pollJob(client, ID, { wait: noWait });

    expect(result.ok).toBe(true);
    expect(get).toHaveBeenCalledTimes(3);
  });
});
