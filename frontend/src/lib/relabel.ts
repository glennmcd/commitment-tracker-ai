import type { Job } from "./jobs";

/** The speakers of a transcript, in order of first speech. */
export function speakersOf(job: Job): string[] {
  return [...new Set((job.transcript ?? []).map((turn) => turn.speaker))];
}

/**
 * The job with two names traded. Diarization can swap two voices, so the visitor can fix it after the results arrive:
 * it is a relabel on the page, not a new job.
 */
export function swapSpeakers(job: Job, a: string, b: string): Job {
  const trade = (name: string | null): string | null => (name === a ? b : name === b ? a : name);
  return {
    ...job,
    transcript: job.transcript?.map((turn) => ({ ...turn, speaker: trade(turn.speaker) ?? turn.speaker })) ?? null,
    analysis: job.analysis
      ? {
          ...job.analysis,
          spans: job.analysis.spans.map((span) => ({
            ...span,
            owner: trade(span.owner),
            recipient: trade(span.recipient),
          })),
        }
      : job.analysis,
  };
}
