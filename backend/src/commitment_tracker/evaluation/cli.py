"""`uv run eval`: run the extractor over a dataset and write a report.

    uv run eval --model claude-opus-5-5 --prompt v1

Calls the real model (and spends money) for every item not already in the response cache.
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from commitment_tracker.evaluation.cache import DEFAULT_CACHE_DIR, ResponseCache
from commitment_tracker.evaluation.dataset import DEV_PATH, DatasetError, load_dataset
from commitment_tracker.evaluation.report import (
    DEFAULT_REPORTS_DIR,
    RunInfo,
    build_report,
    write_report,
)
from commitment_tracker.evaluation.runner import run_items
from commitment_tracker.extractor.factory import build_extractor
from commitment_tracker.extractor.prompt import UnknownPromptVersion
from commitment_tracker.settings import Settings


def _parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval", description=__doc__.split("\n")[0])
    parser.add_argument("--model", default=settings.extractor_model)
    parser.add_argument("--prompt", default=settings.prompt_version, help="prompt version, e.g. v1")
    parser.add_argument(
        "--effort",
        default=settings.extractor_effort,
        choices=["low", "medium", "high", "xhigh", "max"],
    )
    parser.add_argument("--data", type=Path, default=DEV_PATH)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--no-cache", action="store_true", help="always call the model")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    args = _parser(settings).parse_args(argv)
    settings = settings.model_copy(
        update={"prompt_version": args.prompt, "extractor_effort": args.effort}
    )

    try:
        items = load_dataset(args.data)
        extractor = build_extractor(settings, model=args.model)
    except (DatasetError, UnknownPromptVersion) as error:
        print(f"eval: {error}", file=sys.stderr)
        return 2

    started_at, started = datetime.now(UTC), time.perf_counter()
    results = asyncio.run(
        run_items(
            items,
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
        dataset=args.data.name,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
    )
    report = build_report(run, results)
    json_path, md_path = write_report(report, args.reports_dir)

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
