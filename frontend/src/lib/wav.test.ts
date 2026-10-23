import { describe, expect, it } from "vitest";
import { encodeWav, limitSamples, MAX_SECONDS, SAMPLE_RATE } from "./wav";

function text(view: DataView, offset: number, length: number): string {
  return Array.from({ length }, (_, i) => String.fromCharCode(view.getUint8(offset + i))).join("");
}

describe("encodeWav", () => {
  const bytes = encodeWav(Float32Array.from([0, 1, -1, 0.5]));
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  it("writes the 44-byte header the server checks: 16 kHz mono 16-bit PCM", () => {
    expect(bytes.byteLength).toBe(44 + 4 * 2);
    expect(text(view, 0, 4)).toBe("RIFF");
    expect(view.getUint32(4, true)).toBe(36 + 8);
    expect(text(view, 8, 4)).toBe("WAVE");
    expect(text(view, 12, 4)).toBe("fmt ");
    expect(view.getUint32(16, true)).toBe(16);
    expect(view.getUint16(20, true)).toBe(1); // PCM
    expect(view.getUint16(22, true)).toBe(1); // mono
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint32(28, true)).toBe(32_000); // bytes per second
    expect(view.getUint16(32, true)).toBe(2); // block align
    expect(view.getUint16(34, true)).toBe(16);
    expect(text(view, 36, 4)).toBe("data");
    expect(view.getUint32(40, true)).toBe(8);
  });

  it("scales samples to signed 16-bit, with full scale at both ends", () => {
    expect([44, 46, 48, 50].map((offset) => view.getInt16(offset, true))).toEqual([0, 32_767, -32_768, 16_384]);
  });

  it("clips samples outside -1..1", () => {
    const loud = encodeWav(Float32Array.from([2, -3]));
    const v = new DataView(loud.buffer, loud.byteOffset, loud.byteLength);
    expect([v.getInt16(44, true), v.getInt16(46, true)]).toEqual([32_767, -32_768]);
  });

  it("makes a file of exactly 60 seconds the size the upload cap allows", () => {
    const sixty = encodeWav(new Float32Array(MAX_SECONDS * SAMPLE_RATE));
    expect(sixty.byteLength).toBe(1_920_044);
  });
});

describe("limitSamples", () => {
  it("keeps the first 60 seconds and leaves a shorter clip alone", () => {
    const long = new Float32Array(MAX_SECONDS * SAMPLE_RATE + 500);
    expect(limitSamples(long).length).toBe(MAX_SECONDS * SAMPLE_RATE);
    const short = new Float32Array(100);
    expect(limitSamples(short)).toBe(short);
  });
});
