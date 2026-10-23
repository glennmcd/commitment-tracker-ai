import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { startUploadJob, uploadRecording } from "./upload";

const ID = "a".repeat(32);
const ticket = {
  upload_id: ID,
  url: "https://bucket.s3.us-east-2.amazonaws.com/",
  fields: { key: `uploads/${ID}.wav`, "Content-Type": "audio/wav", policy: "p", "x-amz-signature": "s" },
  max_bytes: 1_920_044,
  expires_in: 300,
};

const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });
const failure = (code: string, status: number) => ({
  error: { error: { code, message: "m", details: [] } },
  response: new Response(null, { status }),
});

function client(post: unknown) {
  return { POST: vi.fn(async () => post) } as unknown as ApiClient & { POST: ReturnType<typeof vi.fn> };
}

const wav = new Uint8Array(1000);

describe("uploadRecording", () => {
  it("asks for a ticket, then posts the form fields followed by the file to S3", async () => {
    const posted: { url: string; form: FormData }[] = [];
    const fetchImpl = vi.fn(async (url: string, init: { body: FormData }) => {
      posted.push({ url, form: init.body });
      return new Response(null, { status: 204 });
    });
    const api = client(ok(ticket));

    const result = await uploadRecording(api, wav, fetchImpl as never);

    expect(result).toEqual({ ok: true, uploadId: ID });
    expect(api.POST).toHaveBeenCalledWith("/uploads");
    expect(posted[0]?.url).toBe(ticket.url);
    const keys = [...(posted[0]?.form.keys() ?? [])];
    expect(keys).toEqual(["key", "Content-Type", "policy", "x-amz-signature", "file"]);
    const file = posted[0]?.form.get("file") as File;
    expect(file.size).toBe(1000);
  });

  it("refuses a file over the size the ticket allows, without uploading", async () => {
    const fetchImpl = vi.fn();
    const big = new Uint8Array(ticket.max_bytes + 1);

    const result = await uploadRecording(client(ok(ticket)), big, fetchImpl as never);

    expect(result).toEqual({ ok: false, message: "That recording is longer than 60 seconds." });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("explains an API refusal when asking for the ticket", async () => {
    const result = await uploadRecording(client(failure("rate_limited", 429)), wav, vi.fn() as never);
    expect(result.ok).toBe(false);
    expect(result).toMatchObject({ message: expect.stringContaining("Too many requests") });
  });

  it("says so when storage refuses the file", async () => {
    const fetchImpl = vi.fn(async () => new Response("denied", { status: 403 }));
    const result = await uploadRecording(client(ok(ticket)), wav, fetchImpl as never);
    expect(result).toEqual({ ok: false, message: "The recording could not be uploaded. Try again." });
  });

  it("says so when the network fails", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    const result = await uploadRecording(client(ok(ticket)), wav, fetchImpl as never);
    expect(result).toEqual({
      ok: false,
      message: "Could not reach the API. Check your connection and try again.",
    });
  });
});

describe("startUploadJob", () => {
  it("posts the upload, date and speaker names", async () => {
    const api = client(ok({ job_id: "j".repeat(64), status: "transcribing", latency_ms: {} }, 202));

    const result = await startUploadJob(api, ID, "2026-10-21", ["Ana", "Ben"]);

    expect(api.POST).toHaveBeenCalledWith("/jobs", {
      body: { upload_id: ID, call_date: "2026-10-21", speaker_names: ["Ana", "Ben"] },
    });
    expect(result).toMatchObject({ ok: true });
  });

  it("explains a recording that is not accepted", async () => {
    const result = await startUploadJob(client(failure("audio_too_long", 422)), ID, "2026-10-21", []);
    expect(result).toEqual({ ok: false, message: "That recording is longer than 60 seconds." });
  });
});
