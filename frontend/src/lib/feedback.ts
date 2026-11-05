import type { ApiClient } from "@/api/client";
import { explainFailure, NETWORK } from "./apiErrors";

export type Vote = "up" | "down";

export type FeedbackResult = { ok: true; transcriptKept: boolean } | { ok: false; message: string };

/** Feedback words these three codes its own way; the rest are shared with jobs. */
const FEEDBACK_MESSAGES = {
  job_not_found: "That job has expired, so it can no longer take feedback.",
  job_not_finished: "That job has no results to give feedback on.",
  span_not_found: "That result is no longer there.",
} as const;

/** A vote on one span. With `consent`, the server also keeps the transcript for up to 90 days. */
export async function sendFeedback(
  client: ApiClient,
  jobId: string,
  spanIndex: number,
  vote: Vote,
  consent: boolean,
): Promise<FeedbackResult> {
  try {
    const { data, error, response } = await client.POST("/feedback", {
      body: { job_id: jobId, span_index: spanIndex, vote, consent },
    });
    if (data) return { ok: true, transcriptKept: data.transcript_kept };
    return { ok: false, message: explainFailure(error, response, FEEDBACK_MESSAGES) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}
