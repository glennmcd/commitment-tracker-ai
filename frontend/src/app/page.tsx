import Link from "next/link";
import { Demo } from "@/components/Demo";
import { ResultsTable } from "@/components/evals/ResultsTable";
import { Footer } from "@/components/Footer";
import { PasswordGate } from "@/components/PasswordGate";
import { topResults } from "@/lib/evals";
import { loadIndex } from "@/lib/evalsData";

export default function Home() {
  const top = topResults(loadIndex());
  const preview =
    top.length > 0 ? (
      <section className="top-results" aria-labelledby="top-results">
        <h2 id="top-results">Top results on the held-out test set</h2>
        <ResultsTable
          rows={top}
          caption="The best configurations by ledger F1. Labels is label accuracy over all spans; owner, action and due are field accuracy on matched ledger spans."
        />
      </section>
    ) : null;
  return (
    <main>
      <header className="intro">
        <h1>Commitment Tracker AI</h1>
        <p>Finds who promised what, to whom, and by when in a conversation.</p>
        <p>
          <Link href="/evals/">How well it works: evaluation results</Link>
        </p>
      </header>
      <PasswordGate preview={preview}>
        <Demo />
      </PasswordGate>
      <Footer version={process.env.NEXT_PUBLIC_APP_VERSION} />
    </main>
  );
}
