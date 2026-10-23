import { describe, expect, it } from "vitest";
import { job, span } from "@/test/builders";
import { speakersOf, swapSpeakers } from "./relabel";

const base = job(
  [
    span({ turn_index: 1, owner: "Ana", recipient: "Ben" }),
    span({ turn_index: 0, label: "REQUEST", in_ledger: false, owner: null, recipient: "Ana" }),
    span({ turn_index: 1, label: "REPORTED", in_ledger: false, owner: "Kim", recipient: null }),
  ],
  {
    transcript: [
      { speaker: "Ben", text: "Can you send it?", start_ms: 0, end_ms: 900 },
      { speaker: "Ana", text: "Yes.", start_ms: 1300, end_ms: 1700 },
    ],
  },
);

describe("speakersOf", () => {
  it("lists the speakers in order of first speech", () => {
    expect(speakersOf(base)).toEqual(["Ben", "Ana"]);
  });
});

describe("swapSpeakers", () => {
  const swapped = swapSpeakers(base, "Ben", "Ana");

  it("trades the two names in the transcript and keeps the times", () => {
    expect(swapped.transcript?.map((t) => [t.speaker, t.start_ms])).toEqual([
      ["Ana", 0],
      ["Ben", 1300],
    ]);
  });

  it("trades them as owner and recipient too, and leaves other people alone", () => {
    const spans = swapped.analysis?.spans ?? [];
    expect(spans.map((s) => [s.owner, s.recipient])).toEqual([
      ["Ben", "Ana"],
      [null, "Ben"],
      ["Kim", null],
    ]);
  });

  it("does not change the original", () => {
    expect(base.transcript?.[0]?.speaker).toBe("Ben");
    expect(base.analysis?.spans[0]?.owner).toBe("Ana");
  });

  it("swapping twice gets back to the start", () => {
    expect(swapSpeakers(swapped, "Ben", "Ana")).toEqual(base);
  });
});
