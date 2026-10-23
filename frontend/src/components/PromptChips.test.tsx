import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { parseTranscript } from "@/lib/transcript";
import { PROMPTS, PromptChips } from "./PromptChips";

describe("PROMPTS", () => {
  it.each(PROMPTS.map((p) => [p.id, p.text]))("%s is a conversation the site can send", (_id, text) => {
    const parsed = parseTranscript(text as string);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) expect(parsed.turns.length).toBeGreaterThanOrEqual(2);
  });

  it("covers the hedge and the sarcasm the brief names, with distinct ids and labels", () => {
    expect(PROMPTS.map((p) => p.label)).toEqual(expect.arrayContaining(["Try a hedge", "Try sarcasm"]));
    expect(new Set(PROMPTS.map((p) => p.id)).size).toBe(PROMPTS.length);
    expect(new Set(PROMPTS.map((p) => p.label)).size).toBe(PROMPTS.length);
  });
});

describe("PromptChips", () => {
  it("offers each example as a button and hands over the one pressed", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<PromptChips onPick={onPick} />);

    await user.click(screen.getByRole("button", { name: "Try a hedge" }));

    expect(screen.getAllByRole("button")).toHaveLength(PROMPTS.length);
    expect(onPick).toHaveBeenCalledWith(PROMPTS.find((p) => p.id === "hedge"));
  });

  it("is a named group and can be disabled", () => {
    render(<PromptChips onPick={() => {}} disabled />);
    expect(screen.getByRole("group", { name: "Try to trick it" })).toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  });
});
