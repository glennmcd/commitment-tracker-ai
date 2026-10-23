import type { ApiClient } from "@/api/client";
import { codeOf, explain, NETWORK } from "./jobs";

export type Vote = "up" | "down";

export type FeedbackResult = { ok: true; transcriptKept: boolean } | { ok: false; message: string };

/** The sentence for a feedback failure; the rest are shared with jobs. */
function feedbackMessage(code: string | undefined, retryAfter: string | null): string {
  switch (code) {
    case "job_not_found":
      return "That job has expired, so it can no longer take feedback.";
    case "job_not_finished":
      return "That job has no results to give feedback on.";
    case "span_not_found":
      return "That result is no longer there.";
    default:
      return explain(code, retryAfter);
  }
}

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
    const retryAfter = response.headers.get("retry-after");
    return { ok: false, message: feedbackMessage(codeOf(error), retryAfter) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}
