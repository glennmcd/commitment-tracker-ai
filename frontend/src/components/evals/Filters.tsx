"use client";

import { type ItemFilter, LABEL_ORDER, NO_FILTER, type Verdict } from "@/lib/evals";
import { LABELS, type Label } from "@/lib/labels";

interface Props {
  filter: ItemFilter;
  onChange: (filter: ItemFilter) => void;
  tags: string[];
  provenances: string[];
  judged: boolean; // false for runs whose items can't be judged right or wrong (legacy, audio)
}

/** Native controls only: three selects and a choice of right, wrong or all. */
export function Filters({ filter, onChange, tags, provenances, judged }: Props) {
  const set = (patch: Partial<ItemFilter>) => onChange({ ...filter, ...patch });
  return (
    <form className="filters" aria-label="Filter items" onSubmit={(event) => event.preventDefault()}>
      <label>
        Label
        <select value={filter.label} onChange={(e) => set({ label: e.target.value })}>
          <option value="">Any label</option>
          {LABEL_ORDER.map((label) => (
            <option key={label} value={label}>
              {LABELS[label as Label].name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Tag
        <select value={filter.tag} onChange={(e) => set({ tag: e.target.value })}>
          <option value="">Any tag</option>
          {tags.map((tag) => (
            <option key={tag} value={tag}>
              {tag.replace("_", " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        Written by
        <select value={filter.provenance} onChange={(e) => set({ provenance: e.target.value })}>
          <option value="">Anyone</option>
          {provenances.map((provenance) => (
            <option key={provenance} value={provenance}>
              {provenance}
            </option>
          ))}
        </select>
      </label>
      {judged ? (
        <fieldset className="verdicts">
          <legend>Outcome</legend>
          {(["all", "right", "wrong"] as Verdict[]).map((verdict) => (
            <label key={verdict} className="check">
              <input
                type="radio"
                name="verdict"
                value={verdict}
                checked={filter.verdict === verdict}
                onChange={() => set({ verdict })}
              />
              {verdict === "all" ? "All" : verdict === "right" ? "Right" : "Wrong"}
            </label>
          ))}
        </fieldset>
      ) : null}
      <button type="button" className="secondary" onClick={() => onChange(NO_FILTER)}>
        Clear filters
      </button>
    </form>
  );
}
