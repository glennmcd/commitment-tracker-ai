import { Suspense } from "react";
import { CompareView } from "@/components/evals/CompareView";
import type { RunVerdicts } from "@/lib/evals";
import { loadIndex, loadRun } from "@/lib/evalsData";

/** Each run reduced to its row and per-item verdicts, so the page carries no transcripts. */
function verdicts(): RunVerdicts[] {
  return loadIndex()
    .runs.filter((row) => !row.legacy)
    .map((row) => ({
      row,
      correct: Object.fromEntries(loadRun(row.run).items.map((item) => [item.id, item.correct])),
    }));
}

export default function ComparePage() {
  return (
    <>
      <header className="intro">
        <h1>Compare runs</h1>
        <p>
          Two runs on the same version of a set: how each score moved, and which items went from right to wrong and
          back.
        </p>
      </header>
      {/* useSearchParams needs a Suspense boundary in a static export. */}
      <Suspense fallback={<p className="muted">Loading the runs…</p>}>
        <CompareView runs={verdicts()} />
      </Suspense>
    </>
  );
}
