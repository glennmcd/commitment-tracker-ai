"use client";

import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";
import { type ApiClient, ApiConfigError, getApiClient } from "@/api/client";
import { sendFeedback, type Vote } from "@/lib/feedback";

interface FeedbackState {
  votes: Record<number, Vote>;
  consent: boolean;
  /** The last problem for a span, if its vote did not go through. */
  problems: Record<number, string>;
  busy: boolean;
  setConsent: (next: boolean) => void;
  vote: (spanIndex: number, vote: Vote) => void;
}

const FeedbackContext = createContext<FeedbackState | null>(null);

function clientOrMessage(): ApiClient | string {
  try {
    return getApiClient();
  } catch (error) {
    return error instanceof ApiConfigError ? error.message : "The site is not set up correctly.";
  }
}

/**
 * Holds the visitor's votes on one job's spans and their consent. Ticking or clearing the consent box sends every vote
 * given so far again with the new value, so withdrawing consent also deletes a transcript that was already kept.
 */
export function FeedbackProvider({ jobId, children }: { jobId: string; children: ReactNode }) {
  const [votes, setVotes] = useState<Record<number, Vote>>({});
  const [consent, setConsentState] = useState(false);
  const [problems, setProblems] = useState<Record<number, string>>({});
  const [pending, setPending] = useState(0);
  const latest = useRef({ votes, consent });
  latest.current = { votes, consent };

  const send = useCallback(
    async (spanIndex: number, vote: Vote, withConsent: boolean) => {
      const client = clientOrMessage();
      if (typeof client === "string") {
        setProblems((previous) => ({ ...previous, [spanIndex]: client }));
        return false;
      }
      setPending((n) => n + 1);
      const result = await sendFeedback(client, jobId, spanIndex, vote, withConsent);
      setPending((n) => n - 1);
      setProblems((previous) => {
        const next = { ...previous };
        if (result.ok) delete next[spanIndex];
        else next[spanIndex] = result.message;
        return next;
      });
      return result.ok;
    },
    [jobId],
  );

  const vote = useCallback(
    (spanIndex: number, value: Vote) => {
      void send(spanIndex, value, latest.current.consent).then((ok) => {
        if (ok) setVotes((previous) => ({ ...previous, [spanIndex]: value }));
      });
    },
    [send],
  );

  const setConsent = useCallback(
    (next: boolean) => {
      setConsentState(next);
      for (const [index, value] of Object.entries(latest.current.votes)) void send(Number(index), value, next);
    },
    [send],
  );

  const state = useMemo(
    () => ({ votes, consent, problems, busy: pending > 0, setConsent, vote }),
    [votes, consent, problems, pending, setConsent, vote],
  );
  return <FeedbackContext.Provider value={state}>{children}</FeedbackContext.Provider>;
}

/** Thumbs on one span. Renders nothing outside a FeedbackProvider. */
export function FeedbackButtons({ spanIndex }: { spanIndex: number }) {
  const feedback = useContext(FeedbackContext);
  if (!feedback) return null;
  const current = feedback.votes[spanIndex];
  const problem = feedback.problems[spanIndex];
  return (
    <div className="feedback">
      <fieldset className="thumbs">
        <legend className="sr-only">Was this right?</legend>
        <button
          type="button"
          className="thumb"
          aria-pressed={current === "up"}
          onClick={() => feedback.vote(spanIndex, "up")}
        >
          <span aria-hidden="true">👍</span> Right
        </button>
        <button
          type="button"
          className="thumb"
          aria-pressed={current === "down"}
          onClick={() => feedback.vote(spanIndex, "down")}
        >
          <span aria-hidden="true">👎</span> Wrong
        </button>
      </fieldset>
      <p className="feedback-status" role="status" aria-live="polite">
        {problem ?? (current ? "Thanks, that is noted." : "")}
      </p>
    </div>
  );
}

/** The one consent tickbox for a job's feedback. Renders nothing outside a FeedbackProvider. */
export function ConsentBox() {
  const feedback = useContext(FeedbackContext);
  if (!feedback) return null;
  return (
    <div className="consent">
      <label className="check">
        <input
          type="checkbox"
          checked={feedback.consent}
          onChange={(event) => feedback.setConsent(event.target.checked)}
          aria-describedby="consent-hint"
        />
        <span>Keep this transcript for up to 90 days to improve the labels.</span>
      </label>
      <p id="consent-hint" className="hint">
        Votes on the thumbs are always kept, without the text. Untick this to have the transcript deleted again.
      </p>
    </div>
  );
}
