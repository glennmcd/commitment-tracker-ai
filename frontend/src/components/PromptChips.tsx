"use client";

export interface Prompt {
  id: string;
  label: string;
  text: string;
}

/** Short conversations that invite the model to get it wrong: hedges, sarcasm, conditions, retold promises. */
export const PROMPTS: Prompt[] = [
  {
    id: "hedge",
    label: "Try a hedge",
    text: "Ana: Can you get me the numbers?\nBen: I'll try to get them over to you sometime this week, no promises.",
  },
  {
    id: "sarcasm",
    label: "Try sarcasm",
    text: "Ana: Did legal approve the contract yet?\nBen: Oh sure, I'm certain they'll approve it by tomorrow. They always move so fast.",
  },
  {
    id: "condition",
    label: "Try a condition",
    text: "Ana: When can you start onboarding?\nBen: If procurement approves the PO, we'll start next Tuesday.",
  },
  {
    id: "retold",
    label: "Try a retold promise",
    text: "Ana: Where is the usage report?\nBen: Sarah said she would send it last week, but I haven't seen it.",
  },
  {
    id: "refusal",
    label: "Try a refusal",
    text: "Ana: Can you commit to shipping on the 15th?\nBen: I can't promise the 15th. I'll tell you on Monday what is realistic.",
  },
  {
    id: "smalltalk",
    label: "Try small talk",
    text: "Ana: Our SLA is four hours for priority tickets.\nBen: Good to know. Did you get out in the sun this weekend?",
  },
];

/** Buttons that fill the conversation box with an example. */
export function PromptChips({ onPick, disabled = false }: { onPick: (prompt: Prompt) => void; disabled?: boolean }) {
  return (
    <fieldset className="chips">
      <legend>Try to trick it</legend>
      <ul className="plain chip-list">
        {PROMPTS.map((prompt) => (
          <li key={prompt.id}>
            <button type="button" className="chip" disabled={disabled} onClick={() => onPick(prompt)}>
              {prompt.label}
            </button>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}
