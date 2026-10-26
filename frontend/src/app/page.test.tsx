import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "./page";

afterEach(() => vi.unstubAllEnvs());

describe("the home page", () => {
  it("ends with the release version the build was given", () => {
    vi.stubEnv("NEXT_PUBLIC_APP_VERSION", "1.2.3");
    render(<Home />);

    expect(screen.getByRole("contentinfo")).toHaveTextContent("Version 1.2.3");
  });

  it("keeps the demo behind the password", async () => {
    render(<Home />);

    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByLabelText("Conversation")).not.toBeInTheDocument();
  });

  it("names the product and says what it does", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { level: 1, name: "Commitment Tracker AI" })).toBeInTheDocument();
    expect(screen.getByText(/who promised what, to whom, and by when/i)).toBeInTheDocument();
  });

  it("shows the top three test results while asking for the password", async () => {
    render(<Home />);

    const table = await screen.findByRole("table", { name: /best configurations by ledger F1/i });
    const rows = table.querySelectorAll("tbody tr");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThanOrEqual(3);
  });

  it("links to the evaluation results, which need no password", () => {
    render(<Home />);

    expect(screen.getByRole("link", { name: /evaluation results/i }).getAttribute("href")).toMatch(/^\/evals\/?$/);
  });
});
