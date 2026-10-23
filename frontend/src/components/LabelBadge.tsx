import { LABELS, type Label } from "@/lib/labels";

/** The label as text with a symbol, never colour alone. */
export function LabelBadge({ label, soft = false }: { label: Label; soft?: boolean }) {
  const info = LABELS[label];
  return (
    <span className="badge" data-label={label} title={info.meaning}>
      <span aria-hidden="true">{info.glyph}</span> {info.name}
      {soft ? <span className="soft"> · soft</span> : null}
    </span>
  );
}
