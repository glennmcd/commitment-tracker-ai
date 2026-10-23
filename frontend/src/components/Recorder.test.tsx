import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clock, Recorder } from "./Recorder";

class FakeRecorder {
  static last: FakeRecorder | null = null;
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: unknown) {
    FakeRecorder.last = this;
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"]) });
    this.onstop?.();
  }
}

const trackStop = vi.fn();
const getUserMedia = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  FakeRecorder.last = null;
  trackStop.mockReset();
  getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [{ stop: trackStop }] });
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const wav = new Uint8Array([1, 2, 3]);
const convert = vi.fn(async () => wav);

async function press(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

describe("clock", () => {
  it.each([
    [60_000, "1:00"],
    [59_001, "1:00"],
    [9_000, "0:09"],
    [0, "0:00"],
    [-5, "0:00"],
  ])("shows %i ms as %s", (ms, text) => {
    expect(clock(ms)).toBe(text);
  });
});

describe("Recorder", () => {
  it("tells the visitor what happens to the audio before asking for the microphone", () => {
    render(<Recorder onRecorded={() => {}} convert={convert} />);

    expect(screen.getByText(/sent to be turned into text and analysed, then deleted/)).toBeInTheDocument();
    expect(screen.getByText(/up to 60\s+seconds/)).toBeInTheDocument();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("asks for the microphone only when the button is pressed, then counts down", async () => {
    render(<Recorder onRecorded={() => {}} convert={convert} />);

    await press("Start recording");

    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(screen.getByRole("timer")).toHaveTextContent("Recording · 1:00 left");
    await act(async () => vi.advanceTimersByTime(12_000));
    expect(screen.getByRole("timer")).toHaveTextContent("0:48 left");
  });

  it("stops by itself at 60 seconds and hands over the converted clip", async () => {
    const onRecorded = vi.fn();
    render(<Recorder onRecorded={onRecorded} convert={convert} />);
    await press("Start recording");

    await act(async () => vi.advanceTimersByTime(60_400));

    expect(FakeRecorder.last?.state).toBe("inactive");
    expect(trackStop).toHaveBeenCalled();
    expect(convert).toHaveBeenCalledOnce();
    expect(onRecorded).toHaveBeenLastCalledWith({ wav, durationMs: 60_000 });
    expect(screen.getByText("Recorded 1:00.")).toBeInTheDocument();
  });

  it("stops on request and reports the length", async () => {
    const onRecorded = vi.fn();
    render(<Recorder onRecorded={onRecorded} convert={convert} />);
    await press("Start recording");
    await act(async () => vi.advanceTimersByTime(7_000));

    await press("Stop recording");

    expect(onRecorded).toHaveBeenLastCalledWith({ wav, durationMs: 7_000 });
    expect(screen.getByRole("button", { name: "Record again" })).toBeInTheDocument();
  });

  it("clears the earlier clip when recording again", async () => {
    const onRecorded = vi.fn();
    render(<Recorder onRecorded={onRecorded} convert={convert} />);
    await press("Start recording");
    await press("Stop recording");

    await press("Record again");

    expect(onRecorded).toHaveBeenCalledWith(null);
    expect(screen.getByRole("timer")).toBeInTheDocument();
  });

  it.each([
    ["NotAllowedError", /blocked/],
    ["NotFoundError", /No microphone/],
    ["Other", /could not be made/],
  ])("explains a %s from the browser and offers another go", async (name, message) => {
    getUserMedia.mockRejectedValue(Object.assign(new Error("x"), { name }));
    render(<Recorder onRecorded={() => {}} convert={convert} />);

    await press("Start recording");

    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "Try recording again" })).toBeInTheDocument();
  });

  it("says so when the browser cannot record", async () => {
    vi.stubGlobal("MediaRecorder", undefined);
    render(<Recorder onRecorded={() => {}} convert={convert} />);

    await press("Start recording");

    expect(screen.getByRole("alert")).toHaveTextContent("This browser cannot record");
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("explains a recording that cannot be converted", async () => {
    const failing = vi.fn().mockRejectedValue(new Error("decode"));
    render(<Recorder onRecorded={() => {}} convert={failing} />);
    await press("Start recording");

    await press("Stop recording");

    expect(screen.getByRole("alert")).toHaveTextContent("could not be made");
  });

  it("releases the microphone if it is removed mid-recording", async () => {
    const { unmount } = render(<Recorder onRecorded={() => {}} convert={convert} />);
    await press("Start recording");

    unmount();

    expect(trackStop).toHaveBeenCalled();
  });

  it("disables the button while a job is running", () => {
    render(<Recorder disabled onRecorded={() => {}} convert={convert} />);
    expect(screen.getByRole("button", { name: "Start recording" })).toBeDisabled();
  });
});
