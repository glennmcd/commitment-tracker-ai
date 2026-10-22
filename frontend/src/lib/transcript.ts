export interface TurnInput {
  speaker: string;
  text: string;
}

export type ParseResult = { ok: true; turns: TurnInput[] } | { ok: false; error: string };

// The API's limits (backend schemas.py).
export const MAX_TURNS = 200;
export const MAX_CHARS = 20_000;
const MAX_SPEAKER = 100;

/** One turn per line, written "Speaker: what they said". Blank lines are skipped. */
export function parseTranscript(input: string): ParseResult {
  const turns: TurnInput[] = [];
  const lines = input.split(/\r?\n/);
  for (const [index, raw] of lines.entries()) {
    const line = raw.trim();
    if (!line) continue;
    const colon = line.indexOf(":");
    const speaker = colon > 0 ? line.slice(0, colon).trim() : "";
    const text = colon > 0 ? line.slice(colon + 1).trim() : "";
    if (!speaker || !text || speaker.length > MAX_SPEAKER) {
      return { ok: false, error: `Line ${index + 1} needs a speaker, like “Ana: Hello.”` };
    }
    turns.push({ speaker, text });
  }
  if (turns.length === 0) return { ok: false, error: "Add a few lines of conversation first." };
  if (turns.length > MAX_TURNS) return { ok: false, error: `That is more than ${MAX_TURNS} turns; trim it down.` };
  if (turns.reduce((sum, turn) => sum + turn.text.length, 0) > MAX_CHARS) {
    return { ok: false, error: "That is over 20,000 characters; trim it down." };
  }
  return { ok: true, turns };
}
