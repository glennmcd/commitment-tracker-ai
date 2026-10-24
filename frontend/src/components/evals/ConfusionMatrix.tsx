import type { CSSProperties } from "react";
import { share } from "@/lib/evals";
import { LABELS, type Label } from "@/lib/labels";

/**
 * Expected labels down the side, predicted across the top. Every cell shows its count; the tint behind it is the
 * cell's share of its row and adds nothing the number doesn't say. The table scrolls inside its own box on narrow
 * screens.
 */
export function ConfusionMatrix({ labels, rows }: { labels: string[]; rows: number[][] }) {
  const name = (label: string) => LABELS[label as Label]?.name ?? label;
  return (
    <div className="table-scroll matrix-scroll">
      <table className="data-table matrix">
        <caption>Confusion matrix: rows are expected labels, columns predicted labels</caption>
        <thead>
          <tr>
            <td />
            {labels.map((label) => (
              <th scope="col" key={label}>
                {name(label)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {labels.map((label, r) => {
            const row = rows[r] ?? [];
            return (
              <tr key={label}>
                <th scope="row">{name(label)}</th>
                {row.map((count, c) => (
                  <td
                    key={labels[c]}
                    data-diagonal={r === c ? "true" : undefined}
                    style={{ "--share": share(count, row).toFixed(3) } as CSSProperties}
                  >
                    {count}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
