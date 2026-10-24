"""Agreement between the blind reviewer and the generators, from every staging batch's review log.

Each expected span reviewed contributes one pair: the reviewer's blind label and the generator's.
Rows give the raw agreement and Cohen's kappa per generator (and over all of them), and the raw
agreement per generator label. Low agreement means the "who wrote the data" breakdown measures the
reviewer's labels more than the generator's.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sklearn.metrics import cohen_kappa_score

from commitment_tracker.evaluation.review import load_reviews
from commitment_tracker.evaluation.sets import SETS_DIR, list_sets, load_manifest, set_dir
from commitment_tracker.schemas import Label

ALL = "all"


@dataclass(frozen=True)
class AgreementRow:
    key: str
    spans: int
    agreement: float
    kappa: float | None = None  # None for label rows, and when kappa is undefined (one class)


def _pairs(root: Path) -> dict[str, list[tuple[Label, Label]]]:
    """(mine, generator) label pairs by provenance, over every staging batch with a review log."""
    pairs: dict[str, list[tuple[Label, Label]]] = defaultdict(list)
    for name in list_sets(root):
        manifest = load_manifest(name, root)
        if manifest.role != "staging" or not manifest.sources:
            continue
        provenance = manifest.sources[0].provenance
        for record in load_reviews(set_dir(name, root)):
            pairs[provenance] += [(span.mine, span.generator) for span in record.spans]
    return pairs


def _kappa(pairs: list[tuple[Label, Label]]) -> float | None:
    mine = [m.value for m, _ in pairs]
    theirs = [g.value for _, g in pairs]
    if len(set(mine) | set(theirs)) < 2:
        return None
    kappa = float(cohen_kappa_score(mine, theirs))
    return None if math.isnan(kappa) else kappa


def _row(key: str, pairs: list[tuple[Label, Label]]) -> AgreementRow:
    agreed = sum(m == g for m, g in pairs)
    return AgreementRow(key, len(pairs), agreed / len(pairs), _kappa(pairs))


def agreement(root: Path = SETS_DIR) -> tuple[list[AgreementRow], list[AgreementRow]]:
    """Rows by generator (sorted, then "all") and by generator label (in label order)."""
    by_provenance = _pairs(root)
    if not by_provenance:
        return [], []
    everything = [pair for key in sorted(by_provenance) for pair in by_provenance[key]]
    generators = [_row(key, by_provenance[key]) for key in sorted(by_provenance)]
    generators.append(_row(ALL, everything))
    labels = []
    for label in Label:
        subset = [(m, g) for m, g in everything if g is label]
        if subset:
            row = _row(label.value, subset)
            labels.append(AgreementRow(row.key, row.spans, row.agreement))
    return generators, labels


def render_agreement(rows: tuple[list[AgreementRow], list[AgreementRow]]) -> list[str]:
    generators, labels = rows
    if not generators:
        return ["agreement: no reviewed batches yet"]
    lines = [
        "agreement (blind label against the generator's, by span)",
        f"  {'generator':<24}{'spans':>7}{'agreement':>11}{'kappa':>8}",
    ]
    for row in generators:
        kappa = "n/a" if row.kappa is None else f"{row.kappa:.3f}"
        lines.append(f"  {row.key:<24}{row.spans:>7}{row.agreement:>11.3f}{kappa:>8}")
    lines.append(f"  {'generator label':<24}{'spans':>7}{'agreement':>11}")
    lines += [f"  {row.key:<24}{row.spans:>7}{row.agreement:>11.3f}" for row in labels]
    return lines
