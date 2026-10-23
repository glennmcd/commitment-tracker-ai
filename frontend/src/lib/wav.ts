/** The recording format the server accepts: 16 kHz mono 16-bit PCM in a WAV, at most 60 seconds. */
export const SAMPLE_RATE = 16_000;
export const MAX_SECONDS = 60;

const HEADER_BYTES = 44;

/** The first 60 seconds of the samples (the same array when it is already short enough). */
export function limitSamples(samples: Float32Array): Float32Array {
  const max = MAX_SECONDS * SAMPLE_RATE;
  return samples.length > max ? samples.subarray(0, max) : samples;
}

function writeText(view: DataView, offset: number, value: string): void {
  for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
}

/** A canonical 44-byte-header WAV: the server checks that the header matches the file size exactly. */
export function encodeWav(samples: Float32Array): Uint8Array {
  const dataBytes = samples.length * 2;
  const buffer = new ArrayBuffer(HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);
  writeText(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeText(view, 8, "WAVE");
  writeText(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(view, 36, "data");
  view.setUint32(40, dataBytes, true);
  for (let i = 0; i < samples.length; i++) {
    const clipped = Math.max(-1, Math.min(1, samples[i] ?? 0));
    view.setInt16(HEADER_BYTES + i * 2, Math.round(clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff), true);
  }
  return new Uint8Array(buffer);
}

/**
 * Decodes a recording (WebM/Opus in Chrome and Firefox, MP4/AAC in Safari), mixes it down to mono and resamples it to
 * 16 kHz, then writes the WAV. Everything is the browser's own Web Audio API; there is no library.
 */
export async function recordingToWav(recording: Blob): Promise<Uint8Array> {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await recording.arrayBuffer());
    const frames = Math.max(1, Math.ceil(decoded.duration * SAMPLE_RATE));
    const offline = new OfflineAudioContext(1, frames, SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return encodeWav(limitSamples(rendered.getChannelData(0)));
  } finally {
    await context.close();
  }
}
