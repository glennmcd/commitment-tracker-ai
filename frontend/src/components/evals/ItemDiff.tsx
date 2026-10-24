import { LabelBadge } from "@/components/LabelBadge";
import { type ExpectedSpan, type PredictedSpan, pairSpans, type RunItem } from "@/lib/evals";

/** The fields the scorer checks, each with whether the prediction got it right. */
function differences(expected: ExpectedSpan, predicted: PredictedSpan | undefined): string[] {
  if (!predicted) return ["not found"];
  const notes: string[] = [];
  if (predicted.label !== expected.label) notes.push("label differs");
  if (expected.owner && (predicted.owner ?? "").toLowerCase() !== expected.owner.toLowerCase()) {
    notes.push("owner differs");
  }
  if (expected.due_resolved !== predicted.due_resolved && (expected.due_resolved || predicted.due_resolved)) {
    notes.push("due date differs");
  }
  const action = (predicted.action ?? "").toLowerCase();
  const missing = expected.action_keywords.filter((k) => !action.includes(k));
  if (missing.length) notes.push(`action lacks ${missing.join(", ")}`);
  return notes;
}

function Fields({ span }: { span: ExpectedSpan | PredictedSpan }) {
  const action = "action" in span ? span.action : span.action_keywords.join(", ") || null;
  const rows: [string, string | null][] = [
    ["Owner", span.owner],
    ["To", span.recipient],
    ["action" in span ? "Action" : "Action words", action],
    ["Due", span.due_raw ? `${span.due_raw}${span.due_resolved ? ` → ${span.due_resolved}` : ""}` : null],
    ["Condition", span.condition],
  ];
  const shown = rows.filter(([, value]) => value);
  if (!shown.length) return null;
  return (
    <dl className="facts">
      {shown.map(([term, value]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Verdict({ correct }: { correct: boolean | null }) {
  if (correct === null) return <span className="verdict">Not judged</span>;
  return (
    <span className="verdict" data-correct={correct}>
      <span aria-hidden="true">{correct ? "✓" : "✕"}</span> {correct ? "Right" : "Wrong"}
    </span>
  );
}

/** One item: its transcript, then expected spans beside (or, on a narrow screen, above) predicted spans. */
export function ItemDiff({ item }: { item: RunItem }) {
  const predicted = item.predicted ?? [];
  // Notes only when there is something to judge against: legacy runs have no predicted spans, and audio runs no
  // expected spans on the transcribed turns.
  const judging = item.expected !== null && item.predicted !== null;
  const partners = judging ? pairSpans(item.expected ?? [], predicted) : new Map<number, number>();
  const paired = new Set(partners.values());
  const expected = (item.expected ?? []).map((span, index) => {
    const match = partners.get(index);
    return { span, notes: judging ? differences(span, match === undefined ? undefined : predicted[match]) : [] };
  });
  return (
    <article className="item" id={item.id} aria-labelledby={`${item.id}-title`}>
      <header className="item-head">
        <h3 id={`${item.id}-title`}>{item.id}</h3>
        <Verdict correct={item.correct} />
        <span className="muted">
          {[item.provenance, ...item.tags.map((t) => t.replace("_", " "))].filter(Boolean).join(" · ")}
        </span>
      </header>
      {item.turns ? (
        <ol className="plain turns" start={0}>
          {item.turns.map((turn, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: turns have no id and never reorder
            <li key={index}>
              <span className="muted">[{index}]</span> <span className="speaker">{turn.speaker}:</span> {turn.text}
            </li>
          ))}
        </ol>
      ) : null}
      {item.error ? <p className="problem">Failed: {item.error}</p> : null}
      {item.note ? <p className="hint">Note: {item.note}</p> : null}
      <div className="diff">
        <section aria-label={`Expected for ${item.id}`}>
          <h4>Expected</h4>
          {expected.length === 0 ? <p className="muted">{item.expected_labels.join(", ") || "–"}</p> : null}
          <ul className="plain">
            {expected.map(({ span, notes }, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: spans have no id; two can share turn and quote
              <li key={index} className="span-box">
                <LabelBadge label={span.label} /> <span className="muted">turn {span.turn_index}</span>
                <blockquote>{span.quote}</blockquote>
                <Fields span={span} />
                {notes.length ? (
                  <p className="mismatch">
                    <span aria-hidden="true">✕</span> {notes.join("; ")}
                  </p>
                ) : judging ? (
                  <p className="match">
                    <span aria-hidden="true">✓</span> matched
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
        <section aria-label={`Predicted for ${item.id}`}>
          <h4>Predicted</h4>
          {item.predicted === null ? (
            <p className="muted">Labels only: {item.predicted_labels.join(", ") || "–"}</p>
          ) : null}
          <ul className="plain">
            {predicted.map((span, index) =>
              span.label === "NONE" && !paired.has(index) ? null : (
                // biome-ignore lint/suspicious/noArrayIndexKey: spans have no id; two can share turn and quote
                <li key={index} className="span-box">
                  <LabelBadge label={span.label} /> <span className="muted">turn {span.turn_index}</span>
                  <blockquote>{span.quote}</blockquote>
                  <Fields span={span} />
                  {judging && !paired.has(index) ? (
                    <p className="mismatch">
                      <span aria-hidden="true">✕</span> not expected
                    </p>
                  ) : null}
                </li>
              ),
            )}
          </ul>
          {item.dropped_quotes ? (
            <p className="hint">{item.dropped_quotes} span(s) dropped because their quote was not in the turn.</p>
          ) : null}
        </section>
      </div>
    </article>
  );
}
