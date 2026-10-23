import type { Metadata, Span } from "@/lib/labels";
import { AiMetrics } from "./AiMetrics";
import { FeedbackButtons } from "./Feedback";
import { LabelBadge } from "./LabelBadge";

export function dueText(due: Span["due"]): string {
  if (!due.raw) return "No date given";
  return due.resolved ? `${due.raw} (${due.resolved})` : due.raw;
}

/** One ledger entry: who owes what to whom, by when, and the words that say so. */
export function LedgerCard({ span, index, metrics }: { span: Span; index?: number; metrics?: Metadata }) {
  return (
    <li className="card" data-label={span.label}>
      <div className="card-head">
        <LabelBadge label={span.label} soft={span.soft} />
        {span.ambiguous ? <span className="flag">Ambiguous</span> : null}
        <span className="confidence">{Math.round(span.confidence * 100)}% confident</span>
      </div>
      <p className="who">
        <strong>{span.owner ?? "Nobody named"}</strong>
        {span.recipient ? <> → {span.recipient}</> : null}
      </p>
      <p className="action">{span.action ?? "No action stated"}</p>
      <dl className="facts">
        <div>
          <dt>Due</dt>
          <dd>{dueText(span.due)}</dd>
        </div>
        {span.condition ? (
          <div>
            <dt>Only if</dt>
            <dd>{span.condition}</dd>
          </div>
        ) : null}
      </dl>
      <blockquote>“{span.quote}”</blockquote>
      <p className="rationale">{span.rationale}</p>
      <div className="card-foot">
        {index !== undefined ? <FeedbackButtons spanIndex={index} /> : null}
        {metrics ? <AiMetrics metadata={metrics} /> : null}
      </div>
    </li>
  );
}
