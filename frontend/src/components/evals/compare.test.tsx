import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CompareView } from "@/components/evals/CompareView";
import type { RunVerdicts } from "@/lib/evals";
import { row, singleRun, twoStageRun } from "@/test/evalFixtures";

const navigation = vi.hoisted(() => ({ query: "", replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navigation.query),
  useRouter: () => ({ replace: navigation.replace }),
  usePathname: () => "/evals/compare/",
}));

const verdicts = (run: typeof singleRun) => Object.fromEntries(run.items.map((i) => [i.id, i.correct]));

const RUNS: RunVerdicts[] = [
  { row: row(singleRun.id, "haiku"), correct: verdicts(singleRun) },
  { row: row(twoStageRun.id, "two-stage", { ledger_f1: 0.5 }), correct: verdicts(twoStageRun) },
  { row: row("other-set-run", "opus", { set: "dev", set_sha256: "d".repeat(64) }), correct: {} },
];

beforeEach(() => {
  navigation.query = "";
  navigation.replace.mockReset();
});

describe("the compare view", () => {
  it("asks for two runs until both are chosen", () => {
    render(<CompareView runs={RUNS} />);
    expect(screen.getByText(/choose two runs/i)).toBeInTheDocument();
  });

  it("keeps the choice in the query string", async () => {
    navigation.query = `a=${singleRun.id}`;
    render(<CompareView runs={RUNS} />);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Run B" }), twoStageRun.id);
    expect(navigation.replace).toHaveBeenCalledWith(`/evals/compare/?a=${singleRun.id}&b=${twoStageRun.id}`, {
      scroll: false,
    });
  });

  it("shows score changes and the items that flipped, linked to the later run", () => {
    navigation.query = `a=${singleRun.id}&b=${twoStageRun.id}`;
    render(<CompareView runs={RUNS} />);
    const ledger = screen.getByRole("row", { name: /Ledger F1/ });
    expect(
      within(ledger)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["0.667", "0.500", "−0.167"]);
    const regressions = screen.getByRole("region", { name: "Right in A, wrong in B" });
    expect(within(regressions).getByRole("link", { name: "gem01-01" }).getAttribute("href")).toMatch(
      new RegExp(`^/evals/runs/${twoStageRun.id}/items/?#gem01-01$`),
    );
    const fixes = screen.getByRole("region", { name: "Wrong in A, right in B" });
    expect(within(fixes).getByRole("link", { name: "gem01-02" })).toBeInTheDocument();
    expect(screen.getByText("Right in both: 1. Wrong in both: 0.")).toBeInTheDocument();
  });

  it("refuses runs on different sets", () => {
    navigation.query = `a=${singleRun.id}&b=other-set-run`;
    render(<CompareView runs={RUNS} />);
    expect(screen.getByText(/different sets/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
