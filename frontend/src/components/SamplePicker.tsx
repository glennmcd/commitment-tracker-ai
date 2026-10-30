"use client";

import { clipUrl, type Sample } from "@/lib/samples";

interface Props {
  /** null while the list is loading. */
  samples: Sample[] | null;
  problem: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  disabled?: boolean;
}

function length(ms: number): string {
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Two-person practice calls, made with synthetic voices. Each can be played before it is analysed. */
export function SamplePicker({ samples, problem, selected, onSelect, disabled = false }: Props) {
  if (problem) {
    return (
      <p role="alert" className="problem">
        {problem}
      </p>
    );
  }
  if (samples === null) return <p className="muted">Loading the sample clips…</p>;
  if (samples.length === 0) return <p className="muted">No sample clips are available yet.</p>;

  return (
    <fieldset className="samples">
      <legend>Pick a call</legend>
      <p className="hint">Synthetic voices reading scripted calls, so you can see how a recording is handled.</p>
      <ul className="plain">
        {samples.map((sample) => (
          <li key={sample.id} className="sample" data-selected={selected === sample.id}>
            <label className="sample-choice">
              <input
                type="radio"
                name="sample"
                value={sample.id}
                checked={selected === sample.id}
                onChange={() => onSelect(sample.id)}
                disabled={disabled}
              />
              <span>
                <strong>{sample.title}</strong> <span className="muted">· {length(sample.duration_ms)}</span>
              </span>
            </label>
            <audio controls preload="none" src={clipUrl(sample.id)} aria-label={`Play ${sample.title}`} />
          </li>
        ))}
      </ul>
    </fieldset>
  );
}
