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
});
