"""`uv run eval import|review|promote|rescore`: curate the evaluation sets and their reports."""

import argparse
import sys
from datetime import date
from pathlib import Path

from commitment_tracker.evaluation.importer import (
    BatchError,
    import_batch,
    latest_generation_prompt,
)
from commitment_tracker.evaluation.promote import PromoteError, promote_batch
from commitment_tracker.evaluation.report import DEFAULT_REPORTS_DIR
from commitment_tracker.evaluation.rescore import rescore_set
from commitment_tracker.evaluation.review import review_batch
from commitment_tracker.evaluation.sets import SETS_DIR, SetError


def _import(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="eval import", description="Import a generator's JSONL reply as a staging batch."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--batch", required=True, help="e.g. gem01")
    parser.add_argument("--provenance", required=True, help="hand-written or <family>-<model>")
    parser.add_argument("--generation-prompt", help="default: the latest eval/generation file")
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    args = parser.parse_args(argv)
    try:
        result, _ = import_batch(
            args.file,
            batch=args.batch,
            provenance=args.provenance,
            generation_prompt=args.generation_prompt or latest_generation_prompt(),
            root=args.sets_dir,
            today=date.today(),
        )
    except (BatchError, SetError, OSError) as error:
        print(f"eval import: {error}", file=sys.stderr)
        return 1
    print(
        f"imported {len(result.imported)} | rejected {len(result.rejections)} | "
        f"date disagreements {len(result.date_disagreements)} | "
        f"near duplicates {len(result.near_duplicates)}"
    )
    for rejection in result.rejections:
        print(f"  line {rejection.line}: {rejection.reason}")
    if not result.imported:
        print("eval import: nothing to import; no batch was written", file=sys.stderr)
        return 1
    print(f"staged in {result.directory}; next: uv run eval review --batch {args.batch}")
    return 0


def _review(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="eval review", description="Review a staging batch blind, label by label."
    )
    parser.add_argument("--batch", required=True)
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    args = parser.parse_args(argv)
    try:
        summary = review_batch(args.batch, args.sets_dir)
    except SetError as error:
        print(f"eval review: {error}", file=sys.stderr)
        return 1
    print(
        f"accepted {summary.accepted} | edited {summary.edited} | rejected {summary.rejected} | "
        f"left to review {summary.remaining}"
    )
    if not summary.remaining:
        print(f"next: uv run eval promote --batch {args.batch} --to test")
    return 0


def _promote(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="eval promote", description="Move a reviewed batch's kept items into a set."
    )
    parser.add_argument("--batch", required=True)
    parser.add_argument("--to", required=True, dest="target", help="e.g. test or dev")
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    args = parser.parse_args(argv)
    try:
        result = promote_batch(args.batch, args.target, args.sets_dir, today=date.today())
    except (PromoteError, SetError) as error:
        print(f"eval promote: {error}", file=sys.stderr)
        return 1
    print(f"promoted {len(result.promoted)} into {result.target}; sha256 {result.sha256}")
    if result.gated:
        print(
            f"{result.target} is gated: its hash changed, so the gate now wants a new report and "
            f"baseline (uv run eval --set {result.target})"
        )
    return 0


def _rescore(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="eval rescore", description="Re-score a set's reports from their stored predictions."
    )
    parser.add_argument("--set", dest="set_name", required=True)
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    args = parser.parse_args(argv)
    try:
        outcomes = rescore_set(args.set_name, args.sets_dir, args.reports_dir)
    except SetError as error:
        print(f"eval rescore: {error}", file=sys.stderr)
        return 1
    for outcome in outcomes:
        reason = f" ({outcome.reason})" if outcome.reason else ""
        print(f"{outcome.status:<9} {outcome.path.name}{reason}")
    return 0


SUBCOMMANDS = {"import": _import, "review": _review, "promote": _promote, "rescore": _rescore}
