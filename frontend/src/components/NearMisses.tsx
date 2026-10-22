import type { Span } from "@/lib/labels";
import { LabelBadge } from "./LabelBadge";

/** Spans that look like commitments but are not, with the reason, so a wrong call is easy to spot. */
export function NearMisses({ spans }: { spans: Span[] }) {
  return (
    <section aria-labelledby="near-misses">
      <h2 id="near-misses">Not a commitment</h2>
      {spans.length === 0 ? (
        <p className="muted">Nothing here looked like a near miss.</p>
      ) : (
        <ul className="plain">
          {spans.map((span) => (
            <li key={`${span.turn_index}-${span.quote}`} className="near" data-label={span.label}>
              <LabelBadge label={span.label} />
              <blockquote>“{span.quote}”</blockquote>
              <p className="rationale">{span.rationale}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
