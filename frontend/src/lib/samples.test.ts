import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { clipUrl, fetchSamples, startSampleJob } from "./samples";

const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });
const failure = (code: string, status: number) => ({
  error: { error: { code, message: "m", details: [] } },
  response: new Response(null, { status }),
});

function client(result: unknown) {
  const call = vi.fn(async () => result);
  return { GET: call, POST: call } as unknown as ApiClient & { GET: typeof call; POST: typeof call };
}

describe("clipUrl", () => {
  it("points at the clip the site serves from its own public folder", () => {
    expect(clipUrl("invoice")).toBe("/samples/invoice.wav");
  });
});

describe("fetchSamples", () => {
  it("returns the clips in the order the API lists them", async () => {
    const list = [
      { id: "one", title: "One", duration_ms: 31_000 },
      { id: "two", title: "Two", duration_ms: 42_500 },
    ];
    const api = client(ok(list));

    expect(await fetchSamples(api)).toEqual({ ok: true, samples: list });
    expect(api.GET).toHaveBeenCalledWith("/samples");
  });

  it("explains a refusal", async () => {
    expect(await fetchSamples(client(failure("jobs_unavailable", 503)))).toEqual({
      ok: false,
      message: "The demo is not available right now.",
    });
  });

  it("says so when the API cannot be reached", async () => {
    const api = { GET: vi.fn().mockRejectedValue(new TypeError("x")) } as unknown as ApiClient;
    expect(await fetchSamples(api)).toEqual({
      ok: false,
      message: "Could not reach the API. Check your connection and try again.",
    });
  });
});

describe("startSampleJob", () => {
  it("posts the clip id, the call date and any names", async () => {
    const api = client(ok({ job_id: "j".repeat(64), status: "transcribing", latency_ms: {} }, 202));

    const result = await startSampleJob(api, "invoice", "2026-10-21", ["Dana", "Ravi"]);

    expect(api.POST).toHaveBeenCalledWith("/jobs", {
      body: { sample_id: "invoice", call_date: "2026-10-21", speaker_names: ["Dana", "Ravi"] },
    });
    expect(result).toMatchObject({ ok: true });
  });

  it("explains a clip that is gone", async () => {
    const result = await startSampleJob(client(failure("sample_not_found", 404)), "x", "2026-10-21", []);
    expect(result).toEqual({ ok: false, message: "That sample clip is not available." });
  });
});
