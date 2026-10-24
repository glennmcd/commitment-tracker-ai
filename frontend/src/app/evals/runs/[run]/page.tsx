import Link from "next/link";
import { ConfusionMatrix } from "@/components/evals/ConfusionMatrix";
import { ScoreBars } from "@/components/evals/ScoreBars";
import { dollars, type EvalRun, score, seconds, shortDate, signed } from "@/lib/evals";
import { loadRun, runIds } from "@/lib/evalsData";

export const dynamicParams = false;

export function generateStaticParams(): { run: string }[] {
  return runIds().map((run) => ({ run }));
}

function Headline({ data }: { data: EvalRun }) {
  const { scores } = data;
  const facts: [string, string][] = [
    ["Ledger F1", score(scores.ledger.f1)],
    ["Ledger precision", score(scores.ledger.precision)],
    ["Ledger recall", score(scores.ledger.recall)],
    ["Label accuracy", score(scores.accuracy)],
    ["Macro F1, 8 labels", score(scores.macro_f1)],
    ["Failed items", String(scores.failed_items.length)],
  ];
  return (
    <dl className="headline">
      {facts.map(([term, value]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function RunFacts({ data }: { data: EvalRun }) {
  const { run, scores } = data;
  const rows: [string, string][] = [
    ["Configuration", run.configuration ?? run.model],
    ...Object.entries(run.stages).map(([stage, model]): [string, string] => [`Model, ${stage}`, model]),
    ["Served by", run.served_by.join(", ") || "n/a"],
    ["Prompt", `${run.prompt_version} (sha256 ${run.prompt_sha256.slice(0, 12)})`],
    ["Effort", run.effort],
    ["Set", run.set_sha256 ? `${run.set_name} (sha256 ${run.set_sha256.slice(0, 12)})` : `${data.set}, legacy`],
    ["Items", `${scores.items} (${scores.scored_items} scored; ambiguous items reported apart)`],
    [
      "Latency p50 / p95",
      scores.latency_ms ? `${seconds(scores.latency_ms.p50)} / ${seconds(scores.latency_ms.p95)}` : "n/a",
    ],
    ["Total cost", dollars(scores.cost_usd)],
    ["Cache hits", String(scores.cache_hits)],
    ["Retried items", String(scores.retried_items)],
    ["Quote-check failures", String(scores.quote_failures)],
    ["Started", `${shortDate(run.started_at)} UTC`],
  ];
  return (
    <div className="table-scroll">
      <table className="data-table facts-table">
        <caption>About this run</caption>
        <tbody>
          {rows.map(([term, value]) => (
            <tr key={term}>
              <th scope="row">{term}</th>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function RunPage({ params }: { params: Promise<{ run: string }> }) {
  const { run: id } = await params;
  const data = loadRun(id);
  const { scores } = data;
  const title = `${data.run.configuration ?? data.run.model} on ${data.set}`;
  return (
    <>
      <header className="intro">
        <h1>{title}</h1>
        <p>
          Prompt {data.run.prompt_version}, {shortDate(data.run.started_at)} UTC.{" "}
          {data.legacy ? "Written before evaluation sets existed, so it is not pinned to a set version. " : null}
          <Link href={`/evals/runs/${data.id}/items/`}>See every item</Link>
        </p>
      </header>

      <Headline data={data} />

      {data.audio_scores ? (
        <section aria-labelledby="audio">
          <h2 id="audio">Audio penalty</h2>
          <div className="table-scroll">
            <table className="data-table">
              <caption>Ledger F1 on transcribed clips against the same items as text</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Clips</th>
                  <th scope="col">Audio</th>
                  <th scope="col">Text</th>
                  <th scope="col">Penalty</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.audio_scores.slices).map(([source, slice]) => (
                  <tr key={source}>
                    <th scope="row">{source}</th>
                    <td>{slice.clips}</td>
                    <td>{score(slice.ledger_f1_audio)}</td>
                    <td>{score(slice.ledger_f1_text)}</td>
                    <td>{signed(slice.penalty)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint">
            Turn-count mismatches {data.audio_scores.turn_mismatches}, speaker errors {data.audio_scores.speaker_errors}
            , spans whose turn was not transcribed {data.audio_scores.unmatched_spans}.
          </p>
        </section>
      ) : null}

      <section aria-labelledby="labels">
        <h2 id="labels">By label</h2>
        <ScoreBars labels={scores.labels} />
      </section>

      <section aria-labelledby="confusion">
        <h2 id="confusion">Confusion matrix</h2>
        <ConfusionMatrix labels={scores.confusion.labels} rows={scores.confusion.rows} />
      </section>

      <section aria-labelledby="fields">
        <h2 id="fields">Field accuracy</h2>
        <p className="hint">On ledger spans where both the expected and the predicted label are ledger labels.</p>
        <div className="table-scroll">
          <table className="data-table">
            <caption>Owner, action and due date on matched ledger spans</caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Correct</th>
                <th scope="col">Total</th>
                <th scope="col">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(scores.fields).map(([field, f]) => (
                <tr key={field}>
                  <th scope="row">{field}</th>
                  <td>{f.correct}</td>
                  <td>{f.total}</td>
                  <td>{score(f.accuracy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {Object.keys(data.by_provenance).length > 0 ? (
        <section aria-labelledby="provenance">
          <h2 id="provenance">By who wrote the items</h2>
          <div className="table-scroll">
            <table className="data-table">
              <caption>The same scores over each author's items alone</caption>
              <thead>
                <tr>
                  <th scope="col">Written by</th>
                  <th scope="col">Items</th>
                  <th scope="col">Ledger F1</th>
                  <th scope="col">Precision</th>
                  <th scope="col">Recall</th>
                  <th scope="col">Label accuracy</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.by_provenance).map(([name, p]) => (
                  <tr key={name}>
                    <th scope="row">{name}</th>
                    <td>{p.items}</td>
                    <td>{score(p.ledger_f1)}</td>
                    <td>{score(p.ledger_precision)}</td>
                    <td>{score(p.ledger_recall)}</td>
                    <td>{score(p.accuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {data.two_stage ? (
        <section aria-labelledby="two-stage">
          <h2 id="two-stage">Two-stage pipeline</h2>
          <p className="hint">
            The screen sent {data.two_stage.flagged_turns} of {data.two_stage.turns} turns to the extract model, an
            escalation rate of {score(data.two_stage.escalation_rate)}. On real calls, that rate predicts the saving.
          </p>
          <dl className="headline">
            <div>
              <dt>Escalation rate</dt>
              <dd>{score(data.two_stage.escalation_rate)}</dd>
            </div>
            <div>
              <dt>Screen misses</dt>
              <dd>{data.two_stage.screen_misses}</dd>
            </div>
            {Object.entries(data.two_stage.stage_cost_usd).map(([stage, cost]) => (
              <div key={stage}>
                <dt>Cost, {stage}</dt>
                <dd>{dollars(cost)}</dd>
              </div>
            ))}
          </dl>
          {data.two_stage.screen_miss_items.length > 0 ? (
            <p>Items with a ledger span the screen did not flag: {data.two_stage.screen_miss_items.join(", ")}.</p>
          ) : null}
        </section>
      ) : null}

      {scores.failed_items.length > 0 ? (
        <section aria-labelledby="failed">
          <h2 id="failed">Failed items</h2>
          <ul>
            {scores.failed_items.map((f) => (
              <li key={f.item_id}>
                {f.item_id}: <code>{f.error}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {scores.ambiguous.length > 0 ? (
        <section aria-labelledby="ambiguous">
          <h2 id="ambiguous">Ambiguous items</h2>
          <p className="hint">Tagged ambiguous in the set and left out of the scores above.</p>
          <ul>
            {scores.ambiguous.map((a) => (
              <li key={`${a.item_id}-${a.expected}-${a.predicted}`}>
                {a.item_id}: expected {a.expected}, predicted {a.predicted}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="run">
        <h2 id="run">Run</h2>
        <RunFacts data={data} />
      </section>
    </>
  );
}
