import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { sendFeedback } from "./feedback";

const ID = "a".repeat(64);
const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
const failure = (code: string, status: number) => ({
  error: { error: { code, message: "m", details: [] } },
  response: new Response(null, { status }),
});
const client = (result: unknown) =>
  ({ POST: vi.fn(async () => result) }) as unknown as ApiClient & { POST: ReturnType<typeof vi.fn> };

describe("sendFeedback", () => {
  it("posts the job, span, vote and consent, and says whether the transcript is kept", async () => {
    const api = client(ok({ transcript_kept: true }));

    const result = await sendFeedback(api, ID, 2, "down", true);

    expect(api.POST).toHaveBeenCalledWith("/feedback", {
      body: { job_id: ID, span_index: 2, vote: "down", consent: true },
    });
    expect(result).toEqual({ ok: true, transcriptKept: true });
  });

  it.each([
    ["job_not_found", 404, "That job has expired, so it can no longer take feedback."],
    ["job_not_finished", 409, "That job has no results to give feedback on."],
    ["span_not_found", 404, "That result is no longer there."],
    ["rate_limited", 429, "Too many requests. Try again in a moment."],
  ])("explains %s", async (code, status, message) => {
    expect(await sendFeedback(client(failure(code, status)), ID, 0, "up", false)).toEqual({ ok: false, message });
  });

  it("says so when the API cannot be reached", async () => {
    const api = { POST: vi.fn().mockRejectedValue(new TypeError("x")) } as unknown as ApiClient;
    expect(await sendFeedback(api, ID, 0, "up", false)).toEqual({
      ok: false,
      message: "Could not reach the API. Check your connection and try again.",
    });
  });
});
