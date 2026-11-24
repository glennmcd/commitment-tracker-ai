"""Spans per label and items per provenance for each set, and the labels under a floor.

A label with few spans swings its recall by a large step on one miss, so `eval-stats` shows
the mix before a run. Pure functions over the set summaries from `sets.summarize`; `stats_cli.py`
prints them and sets the exit code.
"""

from commitment_tracker.evaluation.sets import SetSummary, mix
from commitment_tracker.schemas import Label

DEFAULT_FLOOR = 10


def label_counts(summary: SetSummary) -> dict[str, int]:
    """Spans per label in label order, zero for a label the set does not hold."""
    return {label.value: summary.labels.get(label.value, 0) for label in Label}


def thin_labels(summary: SetSummary, floor: int) -> list[str]:
    return [label for label, count in label_counts(summary).items() if count < floor]


def render_stats(summary: SetSummary, floor: int) -> list[str]:
    head = (
        f"{summary.name}  role {summary.role}  gated {'yes' if summary.gated else 'no'}"
        f"  items {summary.items}  sha256 {summary.sha256[:12]}"
    )
    if summary.error is not None:
        return [head, f"  error        {summary.error}"]
    counts = label_counts(summary)
    thin = thin_labels(summary, floor)
    lines = [head]
    for label, count in counts.items():
        marker = "  thin" if label in thin else ""
        lines.append(f"  {label:<12}{count:>3}{marker}")
    lines.append(f"  {'under ' + str(floor):<12}  {', '.join(thin) or 'none'}")
    lines.append(f"  {'provenance':<12}  {mix(summary.provenance)}")
    return lines
