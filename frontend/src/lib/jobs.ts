import type { ApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { explain, explainFailure, NETWORK } from "./apiErrors";
import type { TurnInput } from "./transcript";

export type Job = components["schemas"]["JobResponse"];

export type JobResult = { ok: true; job: Job } | { ok: false; message: string; cancelled?: boolean };

export async function startTextJob(client: ApiClient, transcript: TurnInput[], callDate: string): Promise<JobResult> {
  try {
    const { data, error, response } = await client.POST("/jobs", { body: { transcript, call_date: callDate } });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explainFailure(error, response) };
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
      if (!data) return { ok: false, message: explainFailure(error, response) };
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
