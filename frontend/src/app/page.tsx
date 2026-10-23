import { Demo } from "@/components/Demo";
import { Footer } from "@/components/Footer";

export default function Home() {
  return (
    <main>
      <header className="intro">
        <h1>Commitment Tracker AI</h1>
        <p>Finds who promised what, to whom, and by when in a conversation.</p>
      </header>
      <Demo />
      <Footer version={process.env.NEXT_PUBLIC_APP_VERSION} />
    </main>
  );
}
