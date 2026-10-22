import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { job, span } from "@/test/builders";
import { JobStatus } from "./JobStatus";
import { LedgerCard } from "./LedgerCard";
import { NearMisses } from "./NearMisses";
import { Results } from "./Results";
import { splitTurn, Transcript } from "./Transcript";

describe("LedgerCard", () => {
  it("shows who owes what to whom, when, and the quote", () => {
    render(
      <ul>
        <LedgerCard span={span()} />
      </ul>,
    );

    expect(screen.getByText("Ana")).toBeInTheDocument();
    expect(screen.getByText(/→ Ben/)).toBeInTheDocument();
    expect(screen.getByText("send the countersigned copy")).toBeInTheDocument();
    expect(screen.getByText("by Friday (2026-10-23)")).toBeInTheDocument();
    expect(screen.getByText("“I'll send it by Friday”")).toBeInTheDocument();
    expect(screen.getByText("93% confident")).toBeInTheDocument();
  });

  it("marks a hedged entry as soft in words", () => {
    render(
      <ul>
        <LedgerCard span={span({ label: "HEDGED", soft: true })} />
      </ul>,
    );
    expect(screen.getByText(/Hedged/)).toBeInTheDocument();
    expect(screen.getByText(/soft/)).toBeInTheDocument();
  });

  it("shows the condition of a conditional entry", () => {
    render(
      <ul>
        <LedgerCard span={span({ label: "CONDITIONAL", condition: "legal signs off" })} />
      </ul>,
    );
    expect(screen.getByText("Only if")).toBeInTheDocument();
    expect(screen.getByText("legal signs off")).toBeInTheDocument();
  });

  it("says plainly when there is no owner, date or action", () => {
    const bare = span({
      owner: null,
      recipient: null,
      action: null,
      due: { raw: null, resolved: null, precision: "none" },
    });
    render(
      <ul>
        <LedgerCard span={bare} />
      </ul>,
    );
    expect(screen.getByText("Nobody named")).toBeInTheDocument();
    expect(screen.getByText("No action stated")).toBeInTheDocument();
    expect(screen.getByText("No date given")).toBeInTheDocument();
  });

  it("flags an ambiguous call", () => {
    render(
      <ul>
        <LedgerCard span={span({ ambiguous: true })} />
      </ul>,
    );
    expect(screen.getByText("Ambiguous")).toBeInTheDocument();
  });
});

describe("NearMisses", () => {
  it("lists each near miss with its label and reason", () => {
    const refusal = span({
      label: "REFUSAL",
      in_ledger: false,
      quote: "I can't promise the 15th",
      rationale: "Declines.",
    });
    render(<NearMisses spans={[refusal]} />);

    const section = screen.getByRole("region", { name: "Not a commitment" });
    expect(within(section).getByText(/Refusal/)).toBeInTheDocument();
    expect(within(section).getByText("“I can't promise the 15th”")).toBeInTheDocument();
    expect(within(section).getByText("Declines.")).toBeInTheDocument();
  });

  it("says so when there are none", () => {
    render(<NearMisses spans={[]} />);
    expect(screen.getByText("Nothing here looked like a near miss.")).toBeInTheDocument();
  });
});

describe("splitTurn", () => {
  const text = "Yes. I'll send it by Friday, thanks.";

  it("splits around the quote and rebuilds the text exactly", () => {
    const pieces = splitTurn(text, [span()]);
    expect(pieces.map((p) => p.text)).toEqual(["Yes. ", "I'll send it by Friday", ", thanks."]);
    expect(pieces.map((p) => p.text).join("")).toBe(text);
    expect(pieces[1]?.span?.label).toBe("COMMITMENT");
  });

  it("skips a quote that is not in the turn, an overlapping one, and NONE", () => {
    const missing = span({ quote: "not said" });
    const overlap = span({ label: "HEDGED", quote: "send it by" });
    const none = span({ label: "NONE", quote: "thanks" });
    const pieces = splitTurn(text, [span(), missing, overlap, none]);
    expect(pieces.filter((p) => p.span).map((p) => p.span?.label)).toEqual(["COMMITMENT"]);
    expect(pieces.map((p) => p.text).join("")).toBe(text);
  });

  it("keeps several spans in the order they are spoken", () => {
    const a = span({ quote: "Yes" });
    const b = span({ label: "HEDGED", quote: "thanks" });
    const pieces = splitTurn(text, [b, a]);
    expect(pieces.filter((p) => p.span).map((p) => p.text)).toEqual(["Yes", "thanks"]);
  });
});

describe("Transcript", () => {
  it("marks each quote and names its label for screen readers", () => {
    const j = job([span({ turn_index: 1 })]);
    render(<Transcript turns={j.transcript ?? []} spans={j.analysis?.spans ?? []} />);

    const mark = screen.getByText("I'll send it by Friday", { selector: "mark" });
    expect(mark).toHaveAttribute("data-label", "COMMITMENT");
    expect(within(mark).getByText("Commitment:")).toHaveClass("sr-only");
  });

  it("shows turn times when the turns have them", () => {
    const turns = [{ speaker: "Ana", text: "Hello.", start_ms: 65_000, end_ms: 66_000 }];
    render(<Transcript turns={turns} spans={[]} />);
    expect(screen.getByText("1:05")).toBeInTheDocument();
  });
});

describe("Results", () => {
  it("splits ledger entries from near misses and shows the timing", () => {
    const near = span({
      label: "REQUEST",
      in_ledger: false,
      quote: "Can you send the copy?",
      turn_index: 0,
      rationale: "Asks.",
    });
    render(<Results job={job([span({ turn_index: 1 }), near])} />);

    const ledger = screen.getByRole("region", { name: "Commitments" });
    expect(within(ledger).getAllByRole("listitem")).toHaveLength(1);
    const misses = screen.getByRole("region", { name: "Not a commitment" });
    expect(within(misses).getByText("Asks.")).toBeInTheDocument();
    expect(screen.getByText("Analyze 1.5 s · Total 1.8 s")).toBeInTheDocument();
  });

  it("says when nothing was found", () => {
    render(<Results job={job([])} />);
    expect(screen.getByText("No commitments found in this conversation.")).toBeInTheDocument();
  });
});

describe("JobStatus", () => {
  it("is a polite live region that names each stage", () => {
    const { rerender } = render(<JobStatus status="submitting" />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveTextContent("Sending…");

    rerender(<JobStatus status="analyzing" />);
    expect(region).toHaveTextContent("Finding the commitments…");

    rerender(<JobStatus status={null} />);
    expect(region).toBeEmptyDOMElement();
  });
});
