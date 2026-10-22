"use client";

import { useEffect, useRef, useState } from "react";
import { type ApiClient, ApiConfigError, getApiClient } from "@/api/client";
import { type Job, type JobResult, pollJob, startTextJob } from "@/lib/jobs";
import { speakersOf, swapSpeakers } from "@/lib/relabel";
import { parseTranscript } from "@/lib/transcript";
import { startUploadJob, uploadRecording } from "@/lib/upload";
import { JobStatus } from "./JobStatus";
import { type RecordedClip, Recorder } from "./Recorder";
import { Results } from "./Results";

type Mode = "text" | "record";
type Phase = "idle" | "submitting" | "uploading" | Job["status"];

/** Today in the visitor's own time zone, as the API wants it (YYYY-MM-DD). */
function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Paste a conversation or record one, pick the call date, read the commitments. */
export function Demo() {
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [clip, setClip] = useState<RecordedClip | null>(null);
  const [names, setNames] = useState<[string, string]>(["", ""]);
  const [callDate, setCallDate] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const abort = useRef<AbortController | null>(null);

  // Set after mount: the static page is built on another day and in another time zone.
  useEffect(() => setCallDate(today()), []);
  useEffect(() => () => abort.current?.abort(), []);

  const busy = phase !== "idle" && phase !== "done" && phase !== "failed";

  /** Starts a job with `start`, then follows it to the end. */
  async function run(client: ApiClient, first: Phase, start: () => Promise<JobResult>) {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;

    setPhase(first);
    const started = await start();
    if (controller.signal.aborted) return;
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

  async function analyze(event: React.FormEvent) {
    event.preventDefault();
    setProblem(null);
    setJob(null);

    const parsed = mode === "text" ? parseTranscript(text) : null;
    if (parsed && !parsed.ok) {
      setProblem(parsed.error);
      return;
    }
    if (mode === "record" && !clip) {
      setProblem("Record something first.");
      return;
    }
    let client: ApiClient;
    try {
      client = getApiClient();
    } catch (error) {
      setProblem(error instanceof ApiConfigError ? error.message : "The site is not set up correctly.");
      return;
    }

    if (parsed?.ok) {
      await run(client, "submitting", () => startTextJob(client, parsed.turns, callDate));
    } else if (clip) {
      const speakerNames = names.map((name) => name.trim()).filter(Boolean);
      await run(client, "uploading", async () => {
        const uploaded = await uploadRecording(client, clip.wav);
        if (!uploaded.ok) return uploaded;
        return startUploadJob(client, uploaded.uploadId, callDate, speakerNames);
      });
    }
  }

  const speakers = job ? speakersOf(job) : [];

  return (
    <div className="demo">
      <form onSubmit={analyze} className="panel" noValidate>
        <fieldset className="modes">
          <legend>How do you want to give it a conversation?</legend>
          <label className="mode">
            <input type="radio" name="mode" value="text" checked={mode === "text"} onChange={() => setMode("text")} />
            <span>Type or paste</span>
          </label>
          <label className="mode">
            <input
              type="radio"
              name="mode"
              value="record"
              checked={mode === "record"}
              onChange={() => setMode("record")}
            />
            <span>Record</span>
          </label>
        </fieldset>

        {mode === "text" ? (
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
        ) : (
          <>
            <Recorder disabled={busy} onRecorded={setClip} />
            <div className="field names">
              <p className="hint" id="names-hint">
                Optional: names for the first and the second voice you hear.
              </p>
              <div className="pair">
                {([0, 1] as const).map((i) => (
                  <div key={i}>
                    <label htmlFor={`name-${i}`}>{i === 0 ? "First speaker" : "Second speaker"}</label>
                    <input
                      id={`name-${i}`}
                      type="text"
                      value={names[i]}
                      maxLength={100}
                      placeholder={`Speaker ${i + 1}`}
                      aria-describedby="names-hint"
                      disabled={busy}
                      onChange={(event) =>
                        setNames((previous) => {
                          const next: [string, string] = [previous[0], previous[1]];
                          next[i] = event.target.value;
                          return next;
                        })
                      }
                    />
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

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
          <button type="submit" disabled={busy || !callDate || (mode === "record" && !clip)}>
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
      {job ? (
        <>
          {mode === "record" && speakers.length === 2 ? (
            <p>
              <button
                type="button"
                className="secondary"
                onClick={() => setJob(swapSpeakers(job, speakers[0] as string, speakers[1] as string))}
              >
                Swap the two speakers’ names
              </button>{" "}
              <span className="hint">Use this if the voices were matched to the wrong names.</span>
            </p>
          ) : null}
          <Results job={job} />
        </>
      ) : null}
    </div>
  );
}
