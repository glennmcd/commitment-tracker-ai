import Link from "next/link";
import { ResultsTable } from "@/components/evals/ResultsTable";
import { type AgreementRow, type SetSummary, score, shortDate, signed } from "@/lib/evals";
import { loadIndex } from "@/lib/evalsData";

function mix(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  return entries.length ? entries.map(([key, n]) => `${key} ${n}`).join(", ") : "–";
}

function SetsTable({ sets }: { sets: SetSummary[] }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>Evaluation sets</caption>
        <thead>
          <tr>
            <th scope="col">Set</th>
            <th scope="col">Role</th>
            <th scope="col">Gated</th>
            <th scope="col">Items</th>
            <th scope="col">Review</th>
            <th scope="col">Labels (by span)</th>
            <th scope="col">Written by</th>
            <th scope="col">Hash</th>
          </tr>
        </thead>
        <tbody>
          {sets.map((set) => (
            <tr key={set.name}>
              <th scope="row">
                {set.name}
                {set.description ? <span className="cell-note">{set.description}</span> : null}
              </th>
              <td>{set.kind === "audio" ? "test (audio)" : set.role}</td>
              <td>{set.gated ? "yes" : "no"}</td>
              <td>{set.items}</td>
              <td>{mix(set.review)}</td>
              <td>{mix(set.labels)}</td>
              <td>{mix(set.provenance)}</td>
              <td>
                <code>{set.sha256.slice(0, 12) || "–"}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AgreementTable({ rows }: { rows: AgreementRow[] }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>Blind review: my label against each generator's, by span</caption>
        <thead>
          <tr>
            <th scope="col">Generator</th>
            <th scope="col">Spans</th>
            <th scope="col">Agreement</th>
            <th scope="col">Cohen's kappa</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.key}</th>
              <td>{row.spans}</td>
              <td>{score(row.agreement)}</td>
              <td>{score(row.kappa)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function EvalsPage() {
  const index = loadIndex();
  const tested = Object.entries(index.results).sort(([a], [b]) => (a === "test" ? -1 : b === "test" ? 1 : 0));
  return (
    <>
      <header className="intro">
        <h1>Evaluation</h1>
        <p>
          How well the extractor finds commitments on conversations it was not tuned on. The test set is held out:
          drafted mostly by non-Claude models and by hand, and reviewed blind. The development set is the data the
          prompt was written against, so its scores confirm the pipeline rather than measure it.
        </p>
      </header>

      {tested.length === 0 ? <p className="muted">No evaluation runs have been published yet.</p> : null}
      {tested.map(([set, rows]) => (
        <section key={set} aria-labelledby={`results-${set}`}>
          <h2 id={`results-${set}`}>Results on {set}</h2>
          <ResultsTable rows={rows} caption={`Latest run of each configuration on the ${set} set`} />
        </section>
      ))}

      {index.audio.length > 0 ? (
        <section aria-labelledby="audio">
          <h2 id="audio">Audio penalty</h2>
          <p className="hint">
            Ledger F1 on transcribed clips minus ledger F1 on the same items as text. Polly clips are clean synthetic
            speech; the human slice is two people reading into a laptop microphone.
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <caption>Transcription penalty by configuration and source</caption>
              <thead>
                <tr>
                  <th scope="col">Configuration</th>
                  <th scope="col">Source</th>
                  <th scope="col">Clips</th>
                  <th scope="col">Audio</th>
                  <th scope="col">Text</th>
                  <th scope="col">Penalty</th>
                </tr>
              </thead>
              <tbody>
                {index.audio.flatMap((row) =>
                  Object.entries(row.slices).map(([source, slice]) => (
                    <tr key={`${row.run}-${source}`}>
                      <th scope="row">
                        <Link href={`/evals/runs/${row.run}/`}>{row.configuration}</Link>
                      </th>
                      <td>{source}</td>
                      <td>{slice.clips}</td>
                      <td>{score(slice.ledger_f1_audio)}</td>
                      <td>{score(slice.ledger_f1_text)}</td>
                      <td>{signed(slice.penalty)}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section aria-labelledby="sets">
        <h2 id="sets">The sets</h2>
        <SetsTable sets={index.sets} />
      </section>

      {index.agreement.generators.length > 0 ? (
        <section aria-labelledby="agreement">
          <h2 id="agreement">Review agreement</h2>
          <AgreementTable rows={index.agreement.generators} />
        </section>
      ) : null}

      <section aria-labelledby="runs">
        <h2 id="runs">Every run</h2>
        <ul className="plain run-list">
          {index.runs.map((row) => (
            <li key={row.run}>
              <Link href={`/evals/runs/${row.run}/`}>
                {row.set} · {row.configuration} · prompt {row.prompt_version}
              </Link>{" "}
              <span className="muted">
                {shortDate(row.started_at)} · ledger F1 {score(row.ledger_f1)}
                {row.legacy ? " · legacy, before sets" : ""}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
