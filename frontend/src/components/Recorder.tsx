"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MAX_SECONDS, recordingToWav } from "@/lib/wav";

export interface RecordedClip {
  wav: Uint8Array;
  durationMs: number;
}

interface Props {
  disabled?: boolean;
  onRecorded: (clip: RecordedClip | null) => void;
  /** Turns the recording into the upload format; replaced in tests, since jsdom has no Web Audio. */
  convert?: (recording: Blob) => Promise<Uint8Array>;
  maxSeconds?: number;
}

type Phase = "idle" | "recording" | "processing" | "ready" | "error";

const TICK_MS = 200;

export function clock(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function explainError(error: unknown): string {
  const name = (error as { name?: string } | null)?.name;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Microphone access was blocked. Allow it in your browser's settings, or type text or pick a sample instead.";
  }
  if (name === "NotFoundError") return "No microphone was found. Type text or pick a sample instead.";
  if (name === "Unsupported") return "This browser cannot record. Type text or pick a sample instead.";
  return "The recording could not be made. Try again, or type text instead.";
}

/**
 * Records up to a minute from the microphone. The notice says what happens to the audio before anything asks for the
 * microphone, and the countdown stops the recording by itself at the limit (the server enforces the limit too).
 */
export function Recorder({ disabled = false, onRecorded, convert = recordingToWav, maxSeconds = MAX_SECONDS }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [remainingMs, setRemainingMs] = useState(maxSeconds * 1000);
  const [recordedMs, setRecordedMs] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);

  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAt = useRef(0);
  const cancelled = useRef(false);

  const release = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    for (const track of stream.current?.getTracks() ?? []) track.stop();
    stream.current = null;
  }, []);

  useEffect(
    () => () => {
      cancelled.current = true;
      release();
    },
    [release],
  );

  const stop = useCallback(() => {
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
  }, []);

  async function start() {
    setProblem(null);
    onRecorded(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setProblem(explainError({ name: "Unsupported" }));
      setPhase("error");
      return;
    }
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (cancelled.current) {
        for (const track of media.getTracks()) track.stop();
        return;
      }
      stream.current = media;
      const chunks: Blob[] = [];
      const next = new MediaRecorder(media);
      recorder.current = next;
      next.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      next.onstop = async () => {
        const durationMs = Math.min(Date.now() - startedAt.current, maxSeconds * 1000);
        release();
        if (cancelled.current) return;
        setPhase("processing");
        try {
          const wav = await convert(new Blob(chunks, { type: next.mimeType }));
          if (cancelled.current) return;
          setRecordedMs(durationMs);
          setPhase("ready");
          onRecorded({ wav, durationMs });
        } catch (error) {
          if (cancelled.current) return;
          setProblem(explainError(error));
          setPhase("error");
        }
      };
      startedAt.current = Date.now();
      setRemainingMs(maxSeconds * 1000);
      setPhase("recording");
      next.start();
      timer.current = setInterval(() => {
        const left = maxSeconds * 1000 - (Date.now() - startedAt.current);
        setRemainingMs(Math.max(0, left));
        if (left <= 0) stop();
      }, TICK_MS);
    } catch (error) {
      release();
      setProblem(explainError(error));
      setPhase("error");
    }
  }

  return (
    <div className="recorder">
      {phase === "idle" || phase === "error" ? (
        <>
          <p className="notice" id="recording-notice">
            Your recording is sent to be turned into text and analysed, then deleted. It can be up to {maxSeconds}{" "}
            seconds. Please do not say anything private.
          </p>
          <button type="button" onClick={start} disabled={disabled} aria-describedby="recording-notice">
            {phase === "error" ? "Try recording again" : "Start recording"}
          </button>
        </>
      ) : null}

      {phase === "recording" ? (
        <div className="recording">
          <p className="countdown" role="timer" aria-live="off">
            <span className="dot" aria-hidden="true" /> Recording · <strong>{clock(remainingMs)}</strong> left
          </p>
          <button type="button" onClick={stop}>
            Stop recording
          </button>
        </div>
      ) : null}

      {phase === "processing" ? <p className="muted">Preparing the recording…</p> : null}

      {phase === "ready" ? (
        <div className="ready">
          <p>Recorded {clock(recordedMs)}.</p>
          <button type="button" className="secondary" onClick={start} disabled={disabled}>
            Record again
          </button>
        </div>
      ) : null}

      {problem ? (
        <p role="alert" className="problem">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
