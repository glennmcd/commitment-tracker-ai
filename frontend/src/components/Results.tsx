import type { Job } from "@/lib/jobs";
import { ConsentBox, FeedbackProvider } from "./Feedback";
import { LedgerCard } from "./LedgerCard";
import { NearMisses } from "./NearMisses";
import { Transcript } from "./Transcript";

function seconds(ms: number | null | undefined): string | null {
  return ms == null ? null : `${(ms / 1000).toFixed(1)} s`;
}

export function Results({ job }: { job: Job }) {
  const spans = job.analysis?.spans ?? [];
  // The index is the span's place in the analysis, which is what feedback names.
  const indexed = spans.map((span, index) => ({ span, index }));
  const ledger = indexed.filter(({ span }) => span.in_ledger);
  const near = indexed.filter(({ span }) => !span.in_ledger && span.label !== "NONE");
  const stages = [
    ["Upload", seconds(job.latency_ms.upload_ms)],
    ["Transcribe", seconds(job.latency_ms.transcribe_ms)],
    ["Analyze", seconds(job.latency_ms.analyze_ms)],
    ["Total", seconds(job.latency_ms.total_ms)],
  ].filter((stage): stage is [string, string] => stage[1] !== null);

  return (
    <FeedbackProvider key={job.job_id} jobId={job.job_id}>
      <div className="results">
        <section aria-labelledby="ledger">
          <h2 id="ledger">Commitments</h2>
          {spans.length > 0 ? <ConsentBox /> : null}
          {ledger.length === 0 ? (
            <p className="muted">No commitments found in this conversation.</p>
          ) : (
            <ul className="plain cards">
              {ledger.map(({ span, index }) => (
                <LedgerCard key={`${span.turn_index}-${span.quote}`} span={span} index={index} />
              ))}
            </ul>
          )}
        </section>
        <NearMisses spans={near} />
        <Transcript turns={job.transcript ?? []} spans={spans} />
        {stages.length > 0 ? (
          <p className="muted timing">{stages.map(([name, value]) => `${name} ${value}`).join(" · ")}</p>
        ) : null}
      </div>
    </FeedbackProvider>
  );
}
