import type { ApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import type { TurnInput } from "./transcript";

export type Job = components["schemas"]["JobResponse"];

export type JobResult = { ok: true; job: Job } | { ok: false; message: string; cancelled?: boolean };

const GENERIC = "Something went wrong. Try again.";

/** What the visitor reads for each failure the API can report (error codes: backend api/app.py and worker.py). */
export function explain(code: string | null | undefined, retryAfter: string | null): string {
  switch (code) {
    case "rate_limited":
      return retryAfter
        ? `Too many requests. Try again in ${retryAfter} seconds.`
        : "Too many requests. Try again in a moment.";
    case "daily_budget_exhausted":
      return "The demo has reached its daily limit. Try again tomorrow.";
    case "jobs_unavailable":
      return "The demo is not available right now.";
    case "audio_too_long":
      return "That recording is longer than 60 seconds.";
    case "audio_invalid":
      return "That recording could not be read. Try recording again.";
    case "upload_not_found":
      return "The upload expired. Record again.";
    case "sample_not_found":
      return "That sample clip is not available.";
    case "uploads_unavailable":
      return "Recording is not available right now.";
    case "validation_error":
      return "The API did not accept that request.";
    case "job_not_found":
      return "That job has expired. Run it again.";
    case "model_unavailable":
      return "The model is unavailable right now. Try again in a minute.";
    case "model_output_invalid":
      return "The model's answer could not be read. Try again.";
    case "model_refused":
      return "The model declined to analyse this text.";
    case "transcription_failed":
      return "The recording could not be transcribed.";
    case "no_speech":
      return "No speech was found in the recording.";
    default:
      return GENERIC;
  }
}

export const NETWORK = "Could not reach the API. Check your connection and try again.";

export function codeOf(error: unknown): string | undefined {
  return (error as { error?: { code?: string } } | undefined)?.error?.code;
}

export async function startTextJob(client: ApiClient, transcript: TurnInput[], callDate: string): Promise<JobResult> {
  try {
    const { data, error, response } = await client.POST("/jobs", { body: { transcript, call_date: callDate } });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}

export interface PollOptions {
  onUpdate?: (job: Job) => void;
  signal?: AbortSignal;
  /** Pauses between polls; replaced in tests. */
  wait?: () => Promise<void>;
  maxPolls?: number;
}

const POLL_MS = 1000;
const MAX_POLLS = 150; // two and a half minutes
const MAX_NETWORK_FAILURES = 3;

/** Polls a job once a second until it is done or failed. */
export async function pollJob(client: ApiClient, jobId: string, options: PollOptions = {}): Promise<JobResult> {
  const wait = options.wait ?? (() => new Promise<void>((resolve) => setTimeout(resolve, POLL_MS)));
  const maxPolls = options.maxPolls ?? MAX_POLLS;
  let networkFailures = 0;
  for (let poll = 0; poll < maxPolls; poll++) {
    if (options.signal?.aborted) return { ok: false, message: "Cancelled.", cancelled: true };
    try {
      const { data, error, response } = await client.GET("/jobs/{job_id}", { params: { path: { job_id: jobId } } });
      networkFailures = 0;
      if (!data) return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
      options.onUpdate?.(data);
      if (data.status === "done") return { ok: true, job: data };
      if (data.status === "failed") return { ok: false, message: explain(data.error_code, null) };
    } catch {
      networkFailures++;
      if (networkFailures >= MAX_NETWORK_FAILURES) return { ok: false, message: NETWORK };
    }
    await wait();
  }
  return { ok: false, message: "This is taking longer than expected. Try again." };
}
