import { LabelBadge } from "@/components/LabelBadge";
import { LABEL_ORDER, type LabelScore, score } from "@/lib/evals";
import type { Label } from "@/lib/labels";

/** Precision, recall and F1 per label: the numbers are the content; the bar beside F1 only repeats it. */
export function ScoreBars({ labels }: { labels: Record<string, LabelScore> }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>Scores per label (expected spans as support)</caption>
        <thead>
          <tr>
            <th scope="col">Label</th>
            <th scope="col">Precision</th>
            <th scope="col">Recall</th>
            <th scope="col">F1</th>
            <th scope="col">Support</th>
          </tr>
        </thead>
        <tbody>
          {LABEL_ORDER.filter((label) => label in labels).map((label: Label) => {
            const s = labels[label] as LabelScore;
            return (
              <tr key={label}>
                <th scope="row">
                  <LabelBadge label={label} />
                </th>
                <td>{score(s.precision)}</td>
                <td>{score(s.recall)}</td>
                <td>
                  <span className="bar-cell">
                    {score(s.f1)}
                    <span className="bar" aria-hidden="true">
                      <span style={{ width: `${Math.round(s.f1 * 100)}%` }} />
                    </span>
                  </span>
                </td>
                <td>{s.support}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
