"""`uv run eval-stats`: label and provenance counts per set, with labels under a floor flagged."""

import argparse
import sys
from pathlib import Path

from commitment_tracker.evaluation.sets import SETS_DIR, is_staging, summarize
from commitment_tracker.evaluation.stats import DEFAULT_FLOOR, render_stats, thin_labels


def _floor(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("the floor cannot be negative")
    return value


def stats_main(argv: list[str] | None = None) -> int:
    """`uv run eval-stats`: print each text set's label mix; `--strict` fails on a thin label."""
    parser = argparse.ArgumentParser(
        prog="eval-stats",
        description="Spans per label and items per provenance, per evaluation set.",
    )
    parser.add_argument("--set", dest="set_name", help="one set (default every text set)")
    parser.add_argument(
        "--floor",
        type=_floor,
        default=DEFAULT_FLOOR,
        help=f"spans a label needs (default {DEFAULT_FLOOR})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when a judged set has a label under the floor "
        "(staging sets are judged only with --set)",
    )
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    args = parser.parse_args(argv)

    summaries = [
        summary
        for summary in summarize(args.sets_dir)
        if summary.kind == "text" and args.set_name in (None, summary.name)
    ]
    if not summaries and args.set_name is not None:
        print(f"eval-stats: no text set named {args.set_name!r}", file=sys.stderr)
        return 1

    failed = False
    for summary in summaries:
        print("\n".join(render_stats(summary, args.floor)))
        if summary.error is not None:
            failed = True
            continue
        judged = args.set_name is not None or not is_staging(summary.name)
        if args.strict and judged and thin_labels(summary, args.floor):
            failed = True
            print(
                f"eval-stats: {summary.name} has labels under {args.floor} spans", file=sys.stderr
            )
    return 1 if failed else 0
