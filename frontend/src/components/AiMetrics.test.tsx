import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { metadata } from "@/test/builders";
import { AiMetrics } from "./AiMetrics";

function rows() {
  const panel = screen.getByRole("complementary", { name: "AI metrics" });
  return Object.fromEntries(
    within(panel)
      .getAllByRole("term")
      .map((term) => [term.textContent, term.nextElementSibling?.textContent]),
  );
}

describe("AiMetrics", () => {
  it("shows the model that answered, the prompt, the time, the tokens and the cost", () => {
    render(<AiMetrics metadata={metadata()} />);

    expect(rows()).toEqual({
      Model: "claude-haiku-5-5",
      Prompt: "v1",
      Time: "1.5 s",
      Tokens: "1,234 in · 56 out",
      Cost: "$0.0021",
    });
  });

  it("names the model that answered, not the one asked for, after a fallback", () => {
    render(<AiMetrics metadata={metadata({ model: "claude-haiku-5-5", served_by: "claude-sonnet-5-5" })} />);

    expect(rows().Model).toBe("claude-sonnet-5-5");
  });

  it("leaves out the cost when the model has no known price", () => {
    render(<AiMetrics metadata={metadata({ cost_usd: null })} />);

    expect(rows()).not.toHaveProperty("Cost");
  });

  it("shows a tiny cost as a floor rather than $0.0000", () => {
    render(<AiMetrics metadata={metadata({ cost_usd: 0.00001 })} />);

    expect(rows().Cost).toBe("<$0.0001");
  });

  it("says when the model had to be asked again", () => {
    render(<AiMetrics metadata={metadata({ attempts: 2 })} />);

    expect(rows().Calls).toBe("2 (retried)");
  });

  it("shows only what it is given, and nothing at all when it is given nothing", () => {
    const { container } = render(<AiMetrics metadata={{} as never} />);

    expect(container).toBeEmptyDOMElement();
  });
});
