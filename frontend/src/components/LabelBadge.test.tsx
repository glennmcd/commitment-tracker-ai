import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LABELS, type Label } from "@/lib/labels";
import { LabelBadge } from "./LabelBadge";

const labels = Object.keys(LABELS) as Label[];

describe("LabelBadge", () => {
  it.each(labels)("shows %s as its name and glyph, with the meaning as a title", (label) => {
    const { name, glyph, meaning } = LABELS[label];
    render(<LabelBadge label={label} />);

    const badge = screen.getByTitle(meaning);
    expect(badge).toHaveTextContent(`${glyph} ${name}`);
    expect(badge).toHaveAttribute("data-label", label);
    expect(badge).not.toHaveTextContent("soft");
  });

  it.each(labels)("hides the %s glyph from screen readers but not the name", (label) => {
    const { name, glyph, meaning } = LABELS[label];
    render(<LabelBadge label={label} />);

    const badge = screen.getByTitle(meaning);
    const glyphElement = screen.getByText(glyph);
    expect(glyphElement).toHaveAttribute("aria-hidden", "true");
    expect(glyphElement).not.toHaveTextContent(name);
    expect(badge).not.toHaveAttribute("aria-hidden");
  });

  it("gives every label its own glyph", () => {
    const glyphs = labels.map((label) => LABELS[label].glyph);

    expect(glyphs.every((glyph) => glyph.trim() !== "")).toBe(true);
    expect(new Set(glyphs).size).toBe(glyphs.length);
  });

  it("marks a soft commitment as soft", () => {
    render(<LabelBadge label="COMMITMENT" soft />);

    expect(screen.getByTitle(LABELS.COMMITMENT.meaning)).toHaveTextContent("● Commitment · soft");
  });
});
