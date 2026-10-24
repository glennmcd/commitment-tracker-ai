"""`uv run eval`: run the extractor over an evaluation set and write a report.

    uv run eval --set test --model claude-opus-5-5 --prompt v1
    uv run eval --data some-items.jsonl

Calls the real model (and spends money) for every item not already in the response cache. Set runs
are written to eval/reports/<set>/; `--data` and staging runs go to eval/reports/adhoc/, which is
never gated or published.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from commitment_tracker.evaluation.cache import DEFAULT_CACHE_DIR, ResponseCache
from commitment_tracker.evaluation.dataset import DatasetError, EvalItem, load_dataset
from commitment_tracker.evaluation.report import (
    DEFAULT_REPORTS_DIR,
    RunInfo,
    build_report,
    write_report,
)
from commitment_tracker.evaluation.runner import run_items
from commitment_tracker.evaluation.sets import SETS_DIR, SetError, is_staging, load_set
from commitment_tracker.extractor.factory import build_extractor
from commitment_tracker.extractor.prompt import UnknownPromptVersion
from commitment_tracker.settings import Settings

ADHOC = "adhoc"


@dataclass(frozen=True)
class _Target:
    items: list[EvalItem]
    dataset: str
    reports: str  # the subdirectory of the reports directory
    set_name: str | None = None
    set_sha256: str | None = None


def _parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval", description=__doc__.split("\n")[0])
    parser.add_argument("--model", default=settings.extractor_model)
    parser.add_argument("--prompt", default=settings.prompt_version, help="prompt version, e.g. v1")
    parser.add_argument(
        "--effort",
        default=settings.extractor_effort,
        choices=["low", "medium", "high", "xhigh", "max"],
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--set", dest="set_name", help="a named set under eval/sets (default dev)")
    source.add_argument("--data", type=Path, help="a JSONL file of items, for ad hoc runs")
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--no-cache", action="store_true", help="always call the model")
    return parser


def _target(args: argparse.Namespace) -> _Target:
    if args.data is not None:
        return _Target(load_dataset(args.data), dataset=args.data.name, reports=ADHOC)
    loaded = load_set(args.set_name or "dev", args.sets_dir)
    return _Target(
        loaded.items,
        dataset=loaded.name,
        reports=ADHOC if is_staging(loaded.name) else loaded.name,
        set_name=loaded.name,
        set_sha256=loaded.sha256,
    )


def prompt_versions_with_reports(directory: Path) -> set[str]:
    """Prompt versions that already have a committed report in `directory`."""
    versions: set[str] = set()
    for path in directory.glob("*.json"):
        try:
            versions.add(json.loads(path.read_text(encoding="utf-8"))["run"]["prompt_version"])
        except (ValueError, KeyError, TypeError):
            continue
    return versions


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    args = _parser(settings).parse_args(argv)
    settings = settings.model_copy(
        update={"prompt_version": args.prompt, "extractor_effort": args.effort}
    )

    try:
        target = _target(args)
        extractor = build_extractor(settings, model=args.model)
    except (DatasetError, SetError, UnknownPromptVersion) as error:
        print(f"eval: {error}", file=sys.stderr)
        return 2

    reports_dir = args.reports_dir / target.reports
    if target.set_name == "test":
        # Every look at the test set spends some of its independence; keep the count visible.
        seen = sorted(prompt_versions_with_reports(reports_dir))
        print(f"eval: prompt versions with a test report already: {', '.join(seen) or 'none'}")

    started_at, started = datetime.now(UTC), time.perf_counter()
    results = asyncio.run(
        run_items(
            target.items,
            extractor,
            cache=None if args.no_cache else ResponseCache(args.cache_dir),
            concurrency=args.concurrency,
            effort=args.effort,
        )
    )
    run = RunInfo(
        model=args.model,
        prompt_version=extractor.prompt.version,
        prompt_sha256=extractor.prompt.sha256,
        effort=args.effort,
        dataset=target.dataset,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        set_name=target.set_name,
        set_sha256=target.set_sha256,
        set_items=len(target.items) if target.set_name else None,
    )
    report = build_report(run, results)
    json_path, md_path = write_report(report, reports_dir)

    scores = report.scores
    cost = f"${scores.cost_usd:.4f}" if scores.cost_usd is not None else "n/a"
    print(
        f"ledger F1 {scores.ledger.f1:.3f} | label accuracy {scores.accuracy:.3f} | "
        f"failed {len(scores.failed_items)} | cost {cost} | cache hits {scores.cache_hits}"
    )
    print(f"report: {md_path}")
    print(f"        {json_path}")
    if scores.failed_items:
        # The report is still written, but an incomplete run must not look like a clean one.
        print(
            f"eval: {len(scores.failed_items)} of {scores.items} items failed; see the log above",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
