import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ItemDiff } from "@/components/evals/ItemDiff";
import { ItemsView } from "@/components/evals/ItemsView";
import { item, singleRun, twoStageRun } from "@/test/evalFixtures";

describe("the items view", () => {
  it("shows every item at first, with a count", () => {
    render(<ItemsView run={singleRun} />);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 3 of 3 items");
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("filters to wrong items with a native radio button", async () => {
    render(<ItemsView run={singleRun} />);
    await userEvent.click(screen.getByRole("radio", { name: "Wrong" }));
    expect(screen.getAllByRole("article").map((a) => a.id)).toEqual(["gem01-02"]);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1 of 3 items");
  });

  it("filters by tag, author and label with selects, and clears", async () => {
    render(<ItemsView run={twoStageRun} />);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Written by" }), "hand-written");
    expect(screen.getAllByRole("article").map((a) => a.id)).toEqual(["hand01-01"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Tag" }), "multi_turn");
    expect(screen.getAllByRole("article").map((a) => a.id)).toEqual(["hand01-01"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Label" }), "HEDGED");
    expect(screen.getAllByRole("article").map((a) => a.id)).toEqual(["gem01-01"]);
  });

  it("offers no outcome filter when nothing was judged", () => {
    const legacy = { ...singleRun, items: singleRun.items.map((i) => ({ ...i, correct: null, predicted: null })) };
    render(<ItemsView run={legacy} />);
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });
});

describe("one item", () => {
  it("marks a right item with text and an icon, not colour alone", () => {
    render(<ItemDiff item={item("gem01-01")} />);
    expect(screen.getByText("Right")).toBeInTheDocument();
    expect(screen.getByText("matched")).toBeInTheDocument();
  });

  it("names each field the prediction got wrong", () => {
    const base = item("gem01-02");
    const predicted = base.predicted?.[0];
    if (!predicted) throw new Error("fixture");
    render(
      <ItemDiff
        item={{
          ...base,
          correct: false,
          predicted: [{ ...predicted, label: "HEDGED", owner: "buyer", action: "share it", due_resolved: null }],
          predicted_labels: ["HEDGED"],
        }}
      />,
    );
    expect(screen.getByText("Wrong")).toBeInTheDocument();
    const expected = screen.getByRole("region", { name: "Expected for gem01-02" });
    expect(
      within(expected).getByText(/label differs; owner differs; due date differs; action lacks send/),
    ).toBeInTheDocument();
  });

  it("calls out an expected span that was not found and a prediction that was not expected", () => {
    const base = item("gem01-03");
    const predicted = base.predicted?.[0];
    if (!predicted) throw new Error("fixture");
    render(
      <ItemDiff
        item={{
          ...base,
          correct: false,
          predicted: [{ ...predicted, turn_index: 0, quote: "Can you send the deck?" }],
        }}
      />,
    );
    expect(within(screen.getByRole("region", { name: /^Expected/ })).getByText(/not found/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /^Predicted/ })).getByText(/not expected/)).toBeInTheDocument();
  });

  it("shows the transcript turns with their indices", () => {
    render(<ItemDiff item={item("gem01-01")} />);
    const turns = screen.getAllByRole("listitem").filter((li) => li.textContent?.startsWith("["));
    expect(turns[0]).toHaveTextContent("[0] buyer: Can you send the deck?");
  });
});

describe("pairing like the scorer", () => {
  it("lets one predicted span match only one of two similar expected spans", () => {
    const base = item("gem01-04");
    const first = base.expected?.[0];
    if (!first) throw new Error("fixture");
    const second = { ...first, quote: "I'll send it Friday." };
    render(<ItemDiff item={{ ...base, correct: false, expected: [first, second] }} />);
    const expected = screen.getByRole("region", { name: /^Expected/ });
    expect(within(expected).getAllByText("matched")).toHaveLength(1);
    expect(within(expected).getAllByText(/not found/)).toHaveLength(1);
  });

  it("judges nothing on an audio item, which has no expected spans on the transcribed turns", () => {
    render(<ItemDiff item={{ ...item("gem01-05"), expected: null, correct: null }} />);
    expect(screen.getByText("Not judged")).toBeInTheDocument();
    expect(screen.queryByText(/not expected/)).not.toBeInTheDocument();
    expect(screen.queryByText("matched")).not.toBeInTheDocument();
  });
});
