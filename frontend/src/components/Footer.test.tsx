import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Footer } from "./Footer";

describe("Footer", () => {
  it("shows the version", () => {
    render(<Footer version="0.2.0" />);

    expect(screen.getByRole("contentinfo")).toHaveTextContent("Version 0.2.0");
  });

  it("shows nothing when the build has no version", () => {
    render(<Footer version={undefined} />);

    expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
  });
});
