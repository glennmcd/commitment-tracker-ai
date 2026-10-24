"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { compareRuns, type RunVerdicts, sameSet, score, shortDate, signed } from "@/lib/evals";

function label(run: RunVerdicts): string {
  const { row } = run;
  return `${row.set} · ${row.configuration} · prompt ${row.prompt_version} · ${shortDate(row.started_at)}`;
}

function Flips({ title, ids, run }: { title: string; ids: string[]; run: string }) {
  return (
    <section aria-label={title}>
      <h3>
        {title} ({ids.length})
      </h3>
      {ids.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="plain flips">
          {ids.map((id) => (
            <li key={id}>
              <Link href={`/evals/runs/${run}/items/#${id}`}>{id}</Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Two runs chosen from selects and kept in the query string (?a=…&b=…), so a comparison can be linked. */
export function CompareView({ runs }: { runs: RunVerdicts[] }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const byId = new Map(runs.map((run) => [run.row.run, run]));
  const a = byId.get(params.get("a") ?? "");
  const b = byId.get(params.get("b") ?? "");

  const choose = (key: "a" | "b", value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  const select = (key: "a" | "b", title: string, current: RunVerdicts | undefined) => (
    <label>
      {title}
      <select value={current?.row.run ?? ""} onChange={(event) => choose(key, event.target.value)}>
        <option value="">Choose a run</option>
        {runs.map((run) => (
          <option key={run.row.run} value={run.row.run}>
            {label(run)}
          </option>
        ))}
      </select>
    </label>
  );

  let body = <p className="muted">Choose two runs on the same set to compare.</p>;
  if (a && b && !sameSet(a.row, b.row)) {
    body = (
      <p className="problem">
        These runs are on different sets, or different versions of one set, so their items can't be compared.
      </p>
    );
  } else if (a && b) {
    const comparison = compareRuns(a, b);
    body = (
      <>
        <div className="table-scroll">
          <table className="data-table">
            <caption>Scores, earlier run first</caption>
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">{a.row.configuration} (A)</th>
                <th scope="col">{b.row.configuration} (B)</th>
                <th scope="col">Change</th>
              </tr>
            </thead>
            <tbody>
              {comparison.deltas.map((delta) => (
                <tr key={delta.metric}>
                  <th scope="row">{delta.metric}</th>
                  <td>{score(delta.a)}</td>
                  <td>{score(delta.b)}</td>
                  <td>{delta.a === null || delta.b === null ? "n/a" : signed(delta.b - delta.a)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flip-lists">
          <Flips title="Right in A, wrong in B" ids={comparison.regressions} run={b.row.run} />
          <Flips title="Wrong in A, right in B" ids={comparison.fixes} run={b.row.run} />
        </div>
        <p className="muted">
          Right in both: {comparison.bothRight}. Wrong in both: {comparison.bothWrong}.
        </p>
      </>
    );
  }

  return (
    <>
      <form className="filters" aria-label="Choose runs" onSubmit={(event) => event.preventDefault()}>
        {select("a", "Run A", a)}
        {select("b", "Run B", b)}
      </form>
      {body}
    </>
  );
}
