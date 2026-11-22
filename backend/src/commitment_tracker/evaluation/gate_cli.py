"""`uv run eval-gate`: check the committed evaluation reports against the baseline."""

import argparse
import sys
from pathlib import Path

from commitment_tracker.evaluation.gate import (
    BASELINE_PATH,
    GATED_CONFIGURATIONS,
    Current,
    GateError,
    check,
    load_baseline,
    updated_baseline,
    write_baseline,
)
from commitment_tracker.evaluation.report import DEFAULT_REPORTS_DIR
from commitment_tracker.evaluation.sets import SETS_DIR
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.settings import CONFIGURATIONS, Settings


def gate_current() -> Current:
    """The configuration the gate holds reports to: committed defaults, never the environment."""
    version = Settings.model_fields["prompt_version"].default
    return Current(
        prompt_version=version,
        prompt_sha256=load_prompt(version).sha256,
        effort=Settings.model_fields["extractor_effort"].default,
    )


def gate_main(argv: list[str] | None = None) -> int:
    """`uv run eval-gate`: check committed reports against the baseline; no model calls."""
    parser = argparse.ArgumentParser(
        prog="eval-gate", description="Check committed evaluation reports against the baseline."
    )
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="write the baseline from the latest matching reports (when a change is intended)",
    )
    parser.add_argument(
        "--config",
        action="append",
        choices=list(CONFIGURATIONS),
        help=f"configurations to baseline (default {', '.join(GATED_CONFIGURATIONS)})",
    )
    args = parser.parse_args(argv)
    current = gate_current()
    if args.update_baseline:
        configurations = tuple(args.config or GATED_CONFIGURATIONS)
        try:
            baseline = updated_baseline(
                current,
                configurations,
                args.sets_dir,
                args.reports_dir,
                existing=load_baseline(args.baseline),
            )
        except GateError as error:
            print(f"eval-gate: {error}", file=sys.stderr)
            return 1
        write_baseline(baseline, args.baseline)
        print(f"wrote {args.baseline} for {', '.join(baseline.sets) or 'no sets'}")
        return 0
    result = check(load_baseline(args.baseline), current, args.sets_dir, args.reports_dir)
    for line in result.passes:
        print(f"PASS {line}")
    for line in result.warnings:
        print(f"WARN {line}")
    for line in result.failures:
        print(f"FAIL {line}")
    return 0 if result.ok else 1
