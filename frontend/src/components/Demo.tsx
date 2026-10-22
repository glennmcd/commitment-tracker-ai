"use client";

import { useEffect, useRef, useState } from "react";
import { ApiConfigError, getApiClient } from "@/api/client";
import { type Job, pollJob, startTextJob } from "@/lib/jobs";
import { parseTranscript } from "@/lib/transcript";
import { JobStatus } from "./JobStatus";
import { Results } from "./Results";

type Phase = "idle" | "submitting" | Job["status"];

/** Today in the visitor's own time zone, as the API wants it (YYYY-MM-DD). */
function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Text mode: paste a conversation, pick the call date, read the commitments. */
export function Demo() {
  const [text, setText] = useState("");
  const [callDate, setCallDate] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const abort = useRef<AbortController | null>(null);

  // Set after mount: the static page is built on another day and in another time zone.
  useEffect(() => setCallDate(today()), []);
  useEffect(() => () => abort.current?.abort(), []);

  const busy = phase !== "idle" && phase !== "done" && phase !== "failed";

  async function analyze(event: React.FormEvent) {
    event.preventDefault();
    setProblem(null);
    setJob(null);
    const parsed = parseTranscript(text);
    if (!parsed.ok) {
      setProblem(parsed.error);
      return;
    }
    let client: ReturnType<typeof getApiClient>;
    try {
      client = getApiClient();
    } catch (error) {
      setProblem(error instanceof ApiConfigError ? error.message : "The site is not set up correctly.");
      return;
    }
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;

    setPhase("submitting");
    const started = await startTextJob(client, parsed.turns, callDate);
    if (!started.ok) {
      setPhase("idle");
      setProblem(started.message);
      return;
    }
    setPhase(started.job.status);
    const finished = await pollJob(client, started.job.job_id, {
      signal: controller.signal,
      onUpdate: (update) => !controller.signal.aborted && setPhase(update.status),
    });
    if (controller.signal.aborted) return;
    if (finished.ok) {
      setJob(finished.job);
      setPhase("done");
    } else {
      setPhase("failed");
      setProblem(finished.message);
    }
  }

  return (
    <div className="demo">
      <form onSubmit={analyze} className="panel" noValidate>
        <div className="field">
          <label htmlFor="conversation">Conversation</label>
          <p id="conversation-hint" className="hint">
            One turn per line, written “Speaker: what they said”.
          </p>
          <textarea
            id="conversation"
            name="conversation"
            rows={9}
            value={text}
            onChange={(event) => setText(event.target.value)}
            aria-describedby="conversation-hint"
            aria-invalid={problem !== null && phase === "idle"}
            disabled={busy}
            spellCheck={false}
          />
        </div>
        <div className="field narrow">
          <label htmlFor="call-date">Call date</label>
          <input
            id="call-date"
            name="call-date"
            type="date"
            value={callDate}
            onChange={(event) => setCallDate(event.target.value)}
            required
            disabled={busy}
          />
          <p className="hint">“Friday” and “next week” are worked out from this date.</p>
        </div>
        <div className="actions">
          <button type="submit" disabled={busy || !callDate}>
            {busy ? "Working…" : "Find commitments"}
          </button>
        </div>
      </form>

      <JobStatus status={phase === "idle" ? null : phase} />
      {problem ? (
        <p role="alert" className="problem">
          {problem}
        </p>
      ) : null}
      {job ? <Results job={job} /> : null}
    </div>
  );
}
