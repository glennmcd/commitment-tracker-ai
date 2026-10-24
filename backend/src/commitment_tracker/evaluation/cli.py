"""`uv run eval`: run the extractor over an evaluation set and write a report.

    uv run eval --set test --config two-stage --prompt v1
    uv run eval --set test --model claude-opus-5-5
    uv run eval --data some-items.jsonl
    uv run eval import gemini.jsonl --batch gem01 --provenance gemini-3-pro
    uv run eval review --batch gem01
    uv run eval promote --batch gem01 --to test
    uv run eval rescore --set test
    uv run eval-sets [--agreement]

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
from datetime import UTC, date, datetime
from pathlib import Path

from commitment_tracker.evaluation.agreement import agreement, render_agreement
from commitment_tracker.evaluation.cache import (
    DEFAULT_CACHE_DIR,
    CachedAnalyzer,
    CacheMiss,
    OfflineAdapter,
    ResponseCache,
)
from commitment_tracker.evaluation.compare import (
    CompareError,
    compare,
    find_report,
    render_comparison,
)
from commitment_tracker.evaluation.dataset import DatasetError, EvalItem, load_dataset
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
from commitment_tracker.evaluation.importer import (
    BatchError,
    import_batch,
    latest_generation_prompt,
)
from commitment_tracker.evaluation.promote import PromoteError, promote_batch
from commitment_tracker.evaluation.report import (
    DEFAULT_REPORTS_DIR,
    Report,
    RunInfo,
    build_report,
    write_report,
)
from commitment_tracker.evaluation.rescore import rescore_set
from commitment_tracker.evaluation.review import review_batch
from commitment_tracker.evaluation.runner import request_for, run_items
from commitment_tracker.evaluation.sets import (
    SETS_DIR,
    SetError,
    is_staging,
    load_set,
    render_summary,
    summarize,
)
from commitment_tracker.extractor.analyzer import Analyzer
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.factory import build_analyzer, build_extractor
from commitment_tracker.extractor.prompt import UnknownPromptVersion, load_prompt
from commitment_tracker.extractor.two_stage import TwoStageExtractor
from commitment_tracker.settings import CONFIGURATIONS, Settings, configuration_for_model

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
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--model", help=f"a model id (default {settings.extractor_model})")
    which.add_argument("--config", choices=list(CONFIGURATIONS), help="a named configuration")
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
    cache_mode = parser.add_mutually_exclusive_group()
    cache_mode.add_argument("--no-cache", action="store_true", help="always call the model")
    cache_mode.add_argument(
        "--offline",
        action="store_true",
        help="answer only from the cache; fail before running if any item is missing",
    )
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
        result = import_batch(
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


def sets_main(argv: list[str] | None = None) -> int:
    """`uv run eval-sets`: list the sets; `--agreement` adds the review agreement summary."""
    parser = argparse.ArgumentParser(
        prog="eval-sets", description="List the evaluation sets and what they hold."
    )
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    parser.add_argument(
        "--agreement", action="store_true", help="agreement with generators, from review logs"
    )
    args = parser.parse_args(argv)
    summaries = summarize(args.sets_dir)
    for summary in summaries:
        print("\n".join(render_summary(summary)))
    if args.agreement:
        print("\n".join(render_agreement(agreement(args.sets_dir))))
    return 1 if any(summary.error for summary in summaries) else 0


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
            baseline = updated_baseline(current, configurations, args.sets_dir, args.reports_dir)
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


def compare_main(argv: list[str] | None = None) -> int:
    """`uv run eval-compare <a> <b>`: two runs on the same set, by path or file stem."""
    parser = argparse.ArgumentParser(
        prog="eval-compare", description="Compare two evaluation runs on the same set."
    )
    parser.add_argument("a", help="the earlier run: a report path or its file stem")
    parser.add_argument("b", help="the later run")
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    args = parser.parse_args(argv)
    try:
        a, b = (
            Report.model_validate_json(
                find_report(name, args.reports_dir).read_text(encoding="utf-8")
            )
            for name in (args.a, args.b)
        )
        if a.run.set_name is None:
            raise CompareError("the first report is not a named-set run")
        loaded = load_set(a.run.set_name, args.sets_dir)
        if loaded.sha256 != a.run.set_sha256:
            raise CompareError(f"the runs used an earlier version of {loaded.name}")
        comparison = compare(a, b, {item.id: item for item in loaded.items})
    except (CompareError, SetError) as error:
        print(f"eval-compare: {error}", file=sys.stderr)
        return 1
    print("\n".join(render_comparison(comparison)))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in SUBCOMMANDS:
        return SUBCOMMANDS[argv[0]](argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    args = _parser(settings).parse_args(argv)
    settings = settings.model_copy(
        update={"prompt_version": args.prompt, "extractor_effort": args.effort}
    )

    model = args.model or settings.extractor_model
    configuration = args.config or configuration_for_model(model)
    cache = None if args.no_cache else ResponseCache(args.cache_dir)

    def make(stage_model: str) -> Extractor:
        if args.offline:
            return Extractor(OfflineAdapter(stage_model), load_prompt(args.prompt))
        return build_extractor(settings, model=stage_model)

    def cached(extractor: Extractor) -> Analyzer:
        return CachedAnalyzer(extractor, cache, args.effort)

    try:
        target = _target(args)
        analyzer = (
            build_analyzer(settings, configuration, build=make, wrap=cached)
            if configuration in CONFIGURATIONS
            else cached(make(model))
        )
    except (DatasetError, SetError, UnknownPromptVersion) as error:
        print(f"eval: {error}", file=sys.stderr)
        return 2
    described = analyzer.describe()
    if args.offline:
        first = analyzer.screen if isinstance(analyzer, TwoStageExtractor) else analyzer
        assert isinstance(first, CachedAnalyzer)
        missing = [i.id for i in target.items if not first.is_cached(request_for(i))]
        if missing:
            print(
                f"eval: --offline: {len(missing)} of {len(target.items)} items are not cached "
                f"(first: {missing[0]}); run without --offline to fill the cache",
                file=sys.stderr,
            )
            return 1

    reports_dir = args.reports_dir / target.reports
    if target.set_name == "test":
        # Every look at the test set spends some of its independence; keep the count visible.
        seen = sorted(prompt_versions_with_reports(reports_dir))
        print(f"eval: prompt versions with a test report already: {', '.join(seen) or 'none'}")

    started_at, started = datetime.now(UTC), time.perf_counter()
    try:
        results = asyncio.run(run_items(target.items, analyzer, concurrency=args.concurrency))
    except CacheMiss:
        # Only a two-stage extract window gets here: its keys depend on the screen's labels.
        print(
            "eval: --offline: an extract window is not cached; run without --offline",
            file=sys.stderr,
        )
        return 1
    single = len(described.stages) == 1
    run = RunInfo(
        model=described.stages["extract"] if single else described.name,
        prompt_version=described.prompt_version,
        prompt_sha256=described.prompt_sha256,
        effort=args.effort,
        dataset=target.dataset,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        set_name=target.set_name,
        set_sha256=target.set_sha256,
        set_items=len(target.items) if target.set_name else None,
        configuration=described.name,
        stages=described.stages,
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
