import Link from "next/link";
import { dollars, type RunRow, score, seconds, shortDate } from "@/lib/evals";

/** One row per configuration's latest run on a set: the headline scores, cost and latency. */
export function ResultsTable({ rows, caption }: { rows: RunRow[]; caption: string }) {
  if (rows.length === 0) return <p className="muted">No runs on this set yet.</p>;
  const fields = Object.keys(rows[0]?.fields ?? {});
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Configuration</th>
            <th scope="col">Ledger F1</th>
            <th scope="col">Precision</th>
            <th scope="col">Recall</th>
            <th scope="col">Labels</th>
            {fields.map((field) => (
              <th scope="col" key={field} title={`${field} accuracy on matched ledger spans`}>
                {field[0]?.toUpperCase()}
                {field.slice(1)}
              </th>
            ))}
            <th scope="col">Cost</th>
            <th scope="col">p50 / p95</th>
            <th scope="col">Prompt</th>
            <th scope="col">Run</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.run}>
              <th scope="row">
                {row.configuration}
                {row.legacy ? <span className="tag">legacy, before sets</span> : null}
              </th>
              <td>{score(row.ledger_f1)}</td>
              <td>{score(row.ledger_precision)}</td>
              <td>{score(row.ledger_recall)}</td>
              <td>{score(row.accuracy)}</td>
              {fields.map((field) => (
                <td key={field}>{score(row.fields[field])}</td>
              ))}
              <td>{dollars(row.cost_usd)}</td>
              <td>
                {seconds(row.latency_p50_ms)} / {seconds(row.latency_p95_ms)}
              </td>
              <td>{row.prompt_version}</td>
              <td>
                <Link href={`/evals/runs/${row.run}/`}>{shortDate(row.started_at)}</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
