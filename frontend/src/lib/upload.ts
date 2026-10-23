import type { ApiClient } from "@/api/client";
import { codeOf, explain, type JobResult, NETWORK } from "./jobs";

type FetchLike = (url: string, init: { method: string; body: FormData }) => Promise<Response>;

export type UploadResult = { ok: true; uploadId: string } | { ok: false; message: string };

/**
 * Sends a recording to the audio bucket without passing through the API: ask for a presigned form, then POST its
 * fields and the file to S3. S3 requires the file to be the last field.
 */
export async function uploadRecording(
  client: ApiClient,
  wav: Uint8Array,
  fetchImpl: FetchLike = (url, init) => fetch(url, init),
): Promise<UploadResult> {
  try {
    const { data, error, response } = await client.POST("/uploads");
    if (!data) return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
    if (wav.byteLength > data.max_bytes) return { ok: false, message: explain("audio_too_long", null) };

    const form = new FormData();
    for (const [name, value] of Object.entries(data.fields)) form.append(name, value);
    form.append("file", new Blob([wav as BlobPart], { type: "audio/wav" }), "recording.wav");
    const stored = await fetchImpl(data.url, { method: "POST", body: form });
    if (!stored.ok) return { ok: false, message: "The recording could not be uploaded. Try again." };
    return { ok: true, uploadId: data.upload_id };
  } catch {
    return { ok: false, message: NETWORK };
  }
}

export async function startUploadJob(
  client: ApiClient,
  uploadId: string,
  callDate: string,
  speakerNames: string[],
): Promise<JobResult> {
  try {
    const { data, error, response } = await client.POST("/jobs", {
      body: { upload_id: uploadId, call_date: callDate, speaker_names: speakerNames },
    });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}
