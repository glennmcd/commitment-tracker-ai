import type { components } from "@/api/schema";

export type Label = components["schemas"]["Label"];
export type Span = components["schemas"]["Span"];
export type Metadata = components["schemas"]["Metadata"];
export type Turn = components["schemas"]["Turn"];

interface LabelInfo {
  name: string;
  /** A symbol and a line style give every label a second cue next to its colour (see globals.css). */
  glyph: string;
  meaning: string;
}

export const LABELS: Record<Label, LabelInfo> = {
  COMMITMENT: { name: "Commitment", glyph: "●", meaning: "binds the speaker to a specific action" },
  HEDGED: { name: "Hedged", glyph: "◐", meaning: "names an action but softens the obligation" },
  CONDITIONAL: { name: "Conditional", glyph: "◇", meaning: "depends on a stated condition" },
  SUGGESTION: { name: "Suggestion", glyph: "✦", meaning: "an idea with no owner bound to it" },
  REQUEST: { name: "Request", glyph: "?", meaning: "asks the other party to act" },
  REPORTED: { name: "Reported", glyph: "❝", meaning: "a third party made the promise" },
  REFUSAL: { name: "Refusal", glyph: "✕", meaning: "declines to commit" },
  NONE: { name: "Not a commitment", glyph: "–", meaning: "facts, history or small talk" },
};
