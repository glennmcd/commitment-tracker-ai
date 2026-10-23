import type { Metadata } from "@/lib/labels";

const NUMBER = new Intl.NumberFormat("en-US");

function cost(usd: number): string {
  return usd > 0 && usd < 0.0001 ? "<$0.0001" : `$${usd.toFixed(4)}`;
}

/** What the model call behind an analysis used. Shows only what it is given, and nothing when it has nothing to show. */
export function AiMetrics({ metadata }: { metadata: Partial<Metadata> }) {
  const rows: [string, string][] = [];
  const model = metadata.served_by ?? metadata.model;
  if (model) rows.push(["Model", model]);
  if (metadata.prompt_version) rows.push(["Prompt", metadata.prompt_version]);
  if (metadata.latency_ms != null) rows.push(["Time", `${(metadata.latency_ms / 1000).toFixed(1)} s`]);
  if (metadata.input_tokens != null && metadata.output_tokens != null) {
    rows.push(["Tokens", `${NUMBER.format(metadata.input_tokens)} in · ${NUMBER.format(metadata.output_tokens)} out`]);
  }
  if (metadata.cost_usd != null) rows.push(["Cost", cost(metadata.cost_usd)]);
  if (metadata.attempts != null && metadata.attempts > 1) rows.push(["Calls", `${metadata.attempts} (retried)`]);
  if (rows.length === 0) return null;

  return (
    <aside className="ai-metrics" aria-label="AI metrics">
      <dl>
        {rows.map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
