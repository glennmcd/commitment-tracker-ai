"use client";

import { useEffect, useRef, useState } from "react";
import { clock } from "./Recorder";

interface Props {
  /** The last recording, as the WAV that is uploaded; null until something has been recorded. */
  wav: Uint8Array | null;
}

/**
 * Plays back the last recording so the visitor can hear what will be sent. Every control stays disabled until there
 * is a recording; stop rewinds to the start, and mute is kept when the clip is played again.
 */
export function Playback({ wav }: Props) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [positionMs, setPositionMs] = useState(0);

  useEffect(() => {
    setPlaying(false);
    setPositionMs(0);
    if (!wav) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(new Blob([wav as BlobPart], { type: "audio/wav" }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [wav]);

  const ready = url !== null;

  function toggle() {
    const element = audio.current;
    if (!element) return;
    if (element.paused) {
      element.play().catch(() => setPlaying(false));
    } else {
      element.pause();
    }
  }

  function stop() {
    const element = audio.current;
    if (!element) return;
    element.pause();
    element.currentTime = 0;
    setPlaying(false);
    setPositionMs(0);
  }

  function toggleMute() {
    const element = audio.current;
    if (!element) return;
    element.muted = !element.muted;
    setMuted(element.muted);
  }

  return (
    <fieldset className="playback" disabled={!ready} aria-label="Playback">
      <legend>Playback</legend>
      <audio
        ref={audio}
        src={url ?? undefined}
        preload="auto"
        muted={muted}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setPositionMs(0);
        }}
        onTimeUpdate={(event) => setPositionMs(event.currentTarget.currentTime * 1000)}
      />
      <button type="button" className="secondary" onClick={toggle}>
        {playing ? "Pause" : "Play"}
      </button>
      <button type="button" className="secondary" onClick={stop}>
        Stop
      </button>
      <button type="button" className="secondary" onClick={toggleMute}>
        {muted ? "Unmute" : "Mute"}
      </button>
      <span className="muted position" aria-live="off">
        {clock(positionMs)}
      </span>
    </fieldset>
  );
}
