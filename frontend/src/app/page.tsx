import { Demo } from "@/components/Demo";

export default function Home() {
  return (
    <main>
      <header className="intro">
        <h1>Commitment Tracker AI</h1>
        <p>Finds who promised what, to whom, and by when in a conversation.</p>
      </header>
      <Demo />
    </main>
  );
}
