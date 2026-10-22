import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Home from "./page";

describe("the home page", () => {
  it("names the product and says what it does", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { level: 1, name: "Commitment Tracker AI" })).toBeInTheDocument();
    expect(screen.getByText(/who promised what, to whom, and by when/i)).toBeInTheDocument();
  });
});
