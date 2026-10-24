import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfusionMatrix } from "@/components/evals/ConfusionMatrix";
import { ResultsTable } from "@/components/evals/ResultsTable";
import { ScoreBars } from "@/components/evals/ScoreBars";
import { index, singleRun } from "@/test/evalFixtures";

describe("the results table", () => {
  it("has a row per configuration with its scores and a link to the run", () => {
    render(<ResultsTable rows={index.results.test ?? []} caption="Latest runs" />);
    const table = screen.getByRole("table", { name: "Latest runs" });
    const haiku = within(table).getByRole("row", { name: /haiku/ });
    expect(haiku).toHaveTextContent("0.667");
    // Next drops the trailing slash outside a build with trailingSlash; the build adds it back.
    expect(within(haiku).getByRole("link").getAttribute("href")).toMatch(new RegExp(`^/evals/runs/${singleRun.id}/?$`));
    expect(within(table).getByRole("rowheader", { name: "two-stage" })).toBeInTheDocument();
  });

  it("says when a configuration's latest run predates the sets", () => {
    const rows = [{ ...(index.results.test?.[0] as NonNullable<typeof index.results.test>[number]), legacy: true }];
    render(<ResultsTable rows={rows} caption="Latest runs" />);
    expect(screen.getByText("legacy, before sets")).toBeInTheDocument();
  });

  it("says so when there is nothing to show", () => {
    render(<ResultsTable rows={[]} caption="Latest runs" />);
    expect(screen.getByText(/no runs/i)).toBeInTheDocument();
  });
});

describe("the confusion matrix", () => {
  const labels = ["COMMITMENT", "HEDGED", "NONE"];
  const rows = [
    [3, 1, 0],
    [0, 2, 0],
    [1, 0, 4],
  ];

  it("is a table with expected labels as row headers and predicted labels as column headers", () => {
    render(<ConfusionMatrix labels={labels} rows={rows} />);
    const table = screen.getByRole("table", { name: /rows are expected labels, columns predicted/i });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Commitment", "Hedged", "Not a commitment"]);
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((h) => h.textContent),
    ).toEqual(["Commitment", "Hedged", "Not a commitment"]);
  });

  it("shows every count as text, zeros included", () => {
    render(<ConfusionMatrix labels={labels} rows={rows} />);
    const hedged = screen.getByRole("rowheader", { name: "Hedged" }).closest("tr") as HTMLElement;
    expect(
      within(hedged)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["0", "2", "0"]);
  });

  it("tints each cell by its share of the row and marks the diagonal", () => {
    render(<ConfusionMatrix labels={labels} rows={rows} />);
    const commitment = screen.getByRole("rowheader", { name: "Commitment" }).closest("tr") as HTMLElement;
    const [hit, miss] = within(commitment).getAllByRole("cell");
    expect(hit).toHaveAttribute("data-diagonal", "true");
    expect(hit?.style.getPropertyValue("--share")).toBe("0.750");
    expect(miss?.style.getPropertyValue("--share")).toBe("0.250");
  });
});

describe("the per-label scores", () => {
  it("lists labels in label order with F1 as a number", () => {
    render(<ScoreBars labels={singleRun.scores.labels} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Commitment");
    expect(rows[0]).toHaveTextContent("0.667");
    expect(rows.at(-1)).toHaveTextContent("Not a commitment");
  });
});
