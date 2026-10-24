import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Footer } from "@/components/Footer";

// The pages publish every test transcript; asking search engines not to index them keeps the held-out set a little
// less likely to end up in future training data (docs/plans/part-3-evaluation.md, "Risks").
export const metadata: Metadata = {
  title: "Evaluation · Commitment Tracker AI",
  description: "How the extractor scores on held-out conversations, by model and configuration.",
  robots: { index: false, follow: false },
};

/** The evaluation section. It never renders the password gate: only the demo on / sits behind it. */
export default function EvalsLayout({ children }: { children: ReactNode }) {
  return (
    <main className="evals">
      <nav className="evals-nav" aria-label="Evaluation">
        <Link href="/">Demo</Link>
        <Link href="/evals/">Results</Link>
        <Link href="/evals/compare/">Compare runs</Link>
      </nav>
      {children}
      <Footer version={process.env.NEXT_PUBLIC_APP_VERSION} />
    </main>
  );
}
