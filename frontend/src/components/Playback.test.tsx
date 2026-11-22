import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";
import { Playback } from "./Playback";

const createObjectURL = vi.fn((_: Blob) => "blob:clip");
const revokeObjectURL = vi.fn();
let play: MockInstance<HTMLMediaElement["play"]>;
let pause: MockInstance<HTMLMediaElement["pause"]>;

// jsdom has no media playback, so play and pause only fire the events a browser would.
beforeEach(() => {
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  Object.assign(URL, { createObjectURL, revokeObjectURL });
  play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    Object.defineProperty(this, "paused", { value: false, configurable: true });
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    Object.defineProperty(this, "paused", { value: true, configurable: true });
    this.dispatchEvent(new Event("pause"));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

const wav = new Uint8Array([1, 2, 3]);

function audio(): HTMLAudioElement {
  const element = document.querySelector("audio");
  if (!element) throw new Error("no audio element");
  return element;
}

async function press(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

describe("Playback", () => {
  it("is labelled and disabled until there is a recording", () => {
    render(<Playback wav={null} />);

    expect(screen.getByRole("group", { name: "Playback" })).toBeDisabled();
    for (const name of ["Play", "Stop", "Mute"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("is enabled once a recording is made, and plays that WAV", () => {
    render(<Playback wav={wav} />);

    expect(screen.getByRole("group", { name: "Playback" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Play" })).toBeEnabled();
    expect(createObjectURL.mock.calls[0]?.[0].type).toBe("audio/wav");
    expect(audio()).toHaveAttribute("src", "blob:clip");
  });

  it("starts, pauses and resumes", async () => {
    render(<Playback wav={wav} />);

    await press("Play");
    expect(play).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();

    await press("Pause");
    expect(pause).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("stays on Play when the browser refuses to play", async () => {
    play.mockRejectedValue(new Error("NotAllowedError"));
    render(<Playback wav={wav} />);

    await press("Play");

    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("stops and rewinds to the start", async () => {
    render(<Playback wav={wav} />);
    await press("Play");
    audio().currentTime = 2;
    fireEvent.timeUpdate(audio());
    expect(screen.getByText("0:02")).toBeInTheDocument();

    await press("Stop");

    expect(pause).toHaveBeenCalled();
    expect(audio().currentTime).toBe(0);
    expect(screen.getByText("0:00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("mutes and unmutes", async () => {
    render(<Playback wav={wav} />);

    await press("Mute");
    expect(audio().muted).toBe(true);

    await press("Unmute");
    expect(audio().muted).toBe(false);
    expect(screen.getByRole("button", { name: "Mute" })).toBeInTheDocument();
  });

  it("goes back to Play when the clip ends", async () => {
    render(<Playback wav={wav} />);
    await press("Play");

    fireEvent.ended(audio());

    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("releases the clip when it is replaced or removed", () => {
    const { rerender, unmount } = render(<Playback wav={wav} />);

    rerender(<Playback wav={new Uint8Array([4])} />);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:clip");
    expect(createObjectURL).toHaveBeenCalledTimes(2);

    unmount();
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
  });
});
