import { LABELS, type Span, type Turn } from "@/lib/labels";

type Piece = { text: string; span?: Span };

/** Splits a turn's text around the quotes of its spans, in order, skipping any that overlap an earlier one. */
export function splitTurn(text: string, spans: Span[]): Piece[] {
  const found = spans
    .filter((span) => span.label !== "NONE")
    .map((span) => ({ span, start: text.indexOf(span.quote) }))
    .filter((hit) => hit.start >= 0)
    .sort((a, b) => a.start - b.start);
  const pieces: Piece[] = [];
  let cursor = 0;
  for (const { span, start } of found) {
    if (start < cursor) continue;
    if (start > cursor) pieces.push({ text: text.slice(cursor, start) });
    pieces.push({ text: span.quote, span });
    cursor = start + span.quote.length;
  }
  if (cursor < text.length) pieces.push({ text: text.slice(cursor) });
  return pieces;
}

function clock(ms: number): string {
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function Transcript({ turns, spans }: { turns: Turn[]; spans: Span[] }) {
  return (
    <section aria-labelledby="transcript">
      <h2 id="transcript">Transcript</h2>
      <ol className="plain turns">
        {turns.map((turn, index) => {
          const own = spans.filter((span) => span.turn_index === index);
          return (
            <li key={`${index}-${turn.speaker}`}>
              <span className="speaker">
                {turn.speaker}
                {turn.start_ms != null ? <span className="time"> {clock(turn.start_ms)}</span> : null}
              </span>{" "}
              {splitTurn(turn.text, own).map((piece, i) =>
                piece.span ? (
                  <mark key={`${i}-${piece.text}`} data-label={piece.span.label}>
                    <span className="sr-only">{LABELS[piece.span.label].name}: </span>
                    {piece.text}
                  </mark>
                ) : (
                  <span key={`${i}-${piece.text}`}>{piece.text}</span>
                ),
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
