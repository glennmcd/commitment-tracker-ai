import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SamplePicker } from "./SamplePicker";

const samples = [
  { id: "onboarding-paperwork", title: "Onboarding paperwork", duration_ms: 35_400 },
  { id: "security-review", title: "Security review", duration_ms: 61_000 },
];

describe("SamplePicker", () => {
  it("lists each clip with its length and a player for the site's own copy", () => {
    const { container } = render(<SamplePicker samples={samples} problem={null} selected={null} onSelect={() => {}} />);

    expect(screen.getByRole("radio", { name: /Onboarding paperwork/ })).toBeInTheDocument();
    expect(screen.getByText("· 0:35")).toBeInTheDocument();
    expect(screen.getByText("· 1:01")).toBeInTheDocument();
    const players = container.querySelectorAll("audio");
    expect([...players].map((p) => p.getAttribute("src"))).toEqual([
      "/samples/onboarding-paperwork.wav",
      "/samples/security-review.wav",
    ]);
    expect(screen.getByLabelText("Play Security review")).toHaveAttribute("controls");
  });

  it("reports the choice and shows the selected one", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<SamplePicker samples={samples} problem={null} selected={null} onSelect={onSelect} />);

    await user.click(screen.getByRole("radio", { name: /Security review/ }));
    expect(onSelect).toHaveBeenCalledWith("security-review");

    rerender(<SamplePicker samples={samples} problem={null} selected="security-review" onSelect={onSelect} />);
    expect(screen.getByRole("radio", { name: /Security review/ })).toBeChecked();
  });

  it("does not load audio until it is played", () => {
    const { container } = render(<SamplePicker samples={samples} problem={null} selected={null} onSelect={() => {}} />);
    for (const player of container.querySelectorAll("audio")) expect(player).toHaveAttribute("preload", "none");
  });

  it("says it is loading, empty, or what went wrong", () => {
    const { rerender } = render(<SamplePicker samples={null} problem={null} selected={null} onSelect={() => {}} />);
    expect(screen.getByText("Loading the sample clips…")).toBeInTheDocument();

    rerender(<SamplePicker samples={[]} problem={null} selected={null} onSelect={() => {}} />);
    expect(screen.getByText("No sample clips are available yet.")).toBeInTheDocument();

    rerender(
      <SamplePicker
        samples={null}
        problem="The demo is not available right now."
        selected={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("not available right now");
  });

  it("disables the choices while a job runs", () => {
    render(<SamplePicker samples={samples} problem={null} selected={null} onSelect={() => {}} disabled />);
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
  });
});
