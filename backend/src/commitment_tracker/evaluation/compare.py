"""`uv run eval-compare <a> <b>`: what changed between two runs on the same version of a set.

Headline and per-label scores side by side with the change, then the items that went from right to
wrong and back. An item is right when every expected span gets its expected label and nothing
else is predicted as a ledger, request, refusal or other non-NONE span. Correctness is rebuilt from
each report's stored predictions, so both runs are judged by the current matching code.
"""

from dataclasses import dataclass
from pathlib import Path

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.matching import match
from commitment_tracker.evaluation.report import Report
from commitment_tracker.evaluation.rescore import RescoreError, result_from_detail
from commitment_tracker.schemas import Span


class CompareError(ValueError):
    pass


@dataclass(frozen=True)
class Delta:
    metric: str
    a: float | None
    b: float | None
    digits: int = 3  # decimals to show: 3 for scores, 4 for dollars, 0 for counts and ms

    @property
    def change(self) -> float | None:
        return None if self.a is None or self.b is None else self.b - self.a


@dataclass(frozen=True)
class Comparison:
    a: str
    b: str
    deltas: list[Delta]
    regressions: list[str]  # right in a, wrong in b
    fixes: list[str]  # wrong in a, right in b
    both_right: int
    both_wrong: int


def item_correct(item: EvalItem, predicted: list[Span]) -> bool:
    return all(pair.expected_label == pair.predicted_label for pair in match(item, predicted))


def _correct(report: Report, items: dict[str, EvalItem]) -> dict[str, bool]:
    verdicts = {}
    for detail in report.items:
        try:
            result = result_from_detail(detail, items[detail.item_id], report.run)
        except RescoreError:
            raise CompareError(f"{detail.item_id}: the report has no stored predictions") from None
        except KeyError:
            raise CompareError(f"{detail.item_id} is not in the set") from None
        spans = result.response.spans if result.response else []
        verdicts[detail.item_id] = result.response is not None and item_correct(result.item, spans)
    return verdicts


def _deltas(a: Report, b: Report) -> list[Delta]:
    sa, sb = a.scores, b.scores
    deltas = [
        Delta("ledger F1", sa.ledger.f1, sb.ledger.f1),
        Delta("ledger precision", sa.ledger.precision, sb.ledger.precision),
        Delta("ledger recall", sa.ledger.recall, sb.ledger.recall),
        Delta("label accuracy", sa.accuracy, sb.accuracy),
        Delta("macro F1", sa.macro_f1, sb.macro_f1),
    ]
    deltas += [
        Delta(f"{field} accuracy", sa.fields[field].accuracy, sb.fields[field].accuracy)
        for field in sa.fields
        if field in sb.fields
    ]
    deltas += [
        Delta(f"F1 {label}", sa.labels[label].f1, sb.labels[label].f1)
        for label in sa.labels
        if label in sb.labels
    ]
    deltas += [
        Delta("failed items", len(sa.failed_items), len(sb.failed_items), digits=0),
        Delta("cost USD", sa.cost_usd, sb.cost_usd, digits=4),
        Delta(
            "latency p95 ms",
            sa.latency_ms.p95 if sa.latency_ms else None,
            sb.latency_ms.p95 if sb.latency_ms else None,
            digits=0,
        ),
    ]
    return deltas


def compare(a: Report, b: Report, items: dict[str, EvalItem]) -> Comparison:
    if a.run.set_name != b.run.set_name or a.run.set_sha256 != b.run.set_sha256:
        raise CompareError("the runs are on different sets or different versions of a set")
    right_a, right_b = _correct(a, items), _correct(b, items)
    shared = [item_id for item_id in right_a if item_id in right_b]
    return Comparison(
        a=a.run.configuration or a.run.model,
        b=b.run.configuration or b.run.model,
        deltas=_deltas(a, b),
        regressions=[i for i in shared if right_a[i] and not right_b[i]],
        fixes=[i for i in shared if not right_a[i] and right_b[i]],
        both_right=sum(right_a[i] and right_b[i] for i in shared),
        both_wrong=sum(not right_a[i] and not right_b[i] for i in shared),
    )


def _cell(value: float | None, digits: int) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_comparison(comparison: Comparison) -> list[str]:
    width = max(len(d.metric) for d in comparison.deltas)
    lines = [f"{'metric':<{width}}  {comparison.a:>12}  {comparison.b:>12}  {'change':>8}"]
    for delta in comparison.deltas:
        change = delta.change
        shown = "n/a" if change is None else f"{change:+.{delta.digits}f}"
        a, b = _cell(delta.a, delta.digits), _cell(delta.b, delta.digits)
        lines.append(f"{delta.metric:<{width}}  {a:>12}  {b:>12}  {shown:>8}")
    regressions, fixes = comparison.regressions, comparison.fixes
    lines += [
        "",
        f"right to wrong ({len(regressions)}): {', '.join(regressions) or '-'}",
        f"wrong to right ({len(fixes)}): {', '.join(fixes) or '-'}",
        f"right in both: {comparison.both_right}; wrong in both: {comparison.both_wrong}",
    ]
    return lines


def find_report(name: str, reports_dir: Path) -> Path:
    """A report path as given, or the report with that file stem anywhere under reports_dir."""
    path = Path(name)
    if path.is_file():
        return path
    found = sorted(reports_dir.glob(f"**/{path.stem}.json"))
    if len(found) != 1:
        raise CompareError(f"{len(found)} reports match {name!r} under {reports_dir}")
    return found[0]
