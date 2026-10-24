import Link from "next/link";
import { ItemsView } from "@/components/evals/ItemsView";
import { shortDate } from "@/lib/evals";
import { loadRun, runIds } from "@/lib/evalsData";

export const dynamicParams = false;

export function generateStaticParams(): { run: string }[] {
  return runIds().map((run) => ({ run }));
}

export default async function RunItemsPage({ params }: { params: Promise<{ run: string }> }) {
  const { run: id } = await params;
  const data = loadRun(id);
  return (
    <>
      <header className="intro">
        <h1>
          Items: {data.configuration} on {data.set}
        </h1>
        <p>
          Prompt {data.run.prompt_version}, {shortDate(data.run.started_at)} UTC.{" "}
          <Link href={`/evals/runs/${data.id}/`}>Back to the scores</Link>
        </p>
        {data.audio ? (
          <p className="hint">
            Transcribed audio: each transcript is what Amazon Transcribe heard, and spans point at its turns. Items are
            not marked right or wrong here; the run page has the scores.
          </p>
        ) : null}
        {data.legacy ? (
          <p className="hint">This run predates stored predictions, so only its labels are shown.</p>
        ) : null}
      </header>
      <ItemsView run={data} />
    </>
  );
}
