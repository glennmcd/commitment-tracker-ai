"use client";

import { useMemo, useState } from "react";
import { Filters } from "@/components/evals/Filters";
import { ItemDiff } from "@/components/evals/ItemDiff";
import { distinct, type EvalRun, filterItems, type ItemFilter, NO_FILTER } from "@/lib/evals";

/** Every item of a run, filtered in the browser (a static export has no request-time rendering). */
export function ItemsView({ run }: { run: EvalRun }) {
  const [filter, setFilter] = useState<ItemFilter>(NO_FILTER);
  const shown = useMemo(() => filterItems(run.items, filter), [run.items, filter]);
  const judged = run.items.some((item) => item.correct !== null);
  return (
    <>
      <Filters
        filter={filter}
        onChange={setFilter}
        tags={distinct(run.items.flatMap((item) => item.tags))}
        provenances={distinct(run.items.map((item) => item.provenance))}
        judged={judged}
      />
      <p role="status" className="muted">
        Showing {shown.length} of {run.items.length} items
        {judged ? ` · ${run.items.filter((item) => item.correct === false).length} wrong in all` : ""}
      </p>
      {shown.map((item) => (
        <ItemDiff key={item.id} item={item} />
      ))}
    </>
  );
}
