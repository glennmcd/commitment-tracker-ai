"""`uv run eval`: run the extractor over an evaluation set and write a report.

    uv run eval --set test --config two-stage --prompt v1
    uv run eval --set test --model claude-opus-5-5
    uv run eval --data some-items.jsonl
    uv run eval --set test --config opus --estimate
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
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from commitment_tracker.evaluation.agreement import agreement, render_agreement
from commitment_tracker.evaluation.audio import (
    AudioClip,
    load_clips,
    source_items,
)
from commitment_tracker.evaluation.audio_eval import (
    Alignment,
    AwsClipTranscriber,
    Transcribe,
    TranscriptCache,
    align,
    audio_scores,
)
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
from commitment_tracker.evaluation.curation_cli import SUBCOMMANDS
from commitment_tracker.evaluation.dataset import (
    DatasetError,
    EvalItem,
    canonical_sha256,
    load_dataset,
)
from commitment_tracker.evaluation.estimate import estimate_run, render_estimate
from commitment_tracker.evaluation.report import (
    DEFAULT_REPORTS_DIR,
    Report,
    RunInfo,
    build_report,
    write_report,
)
from commitment_tracker.evaluation.runner import request_for, run_items
from commitment_tracker.evaluation.sets import (
    SETS_DIR,
    SetError,
    is_staging,
    load_manifest,
    load_set,
    render_summary,
    set_dir,
    summarize,
)
from commitment_tracker.evaluation.site_export import SITE_DATA_DIR, export_site
from commitment_tracker.extractor.analyzer import Analyzer
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.factory import build_analyzer, build_extractor
from commitment_tracker.extractor.prompt import UnknownPromptVersion, load_prompt
from commitment_tracker.extractor.two_stage import TwoStageExtractor
from commitment_tracker.settings import CONFIGURATIONS, Settings, configuration_for_model

ADHOC = "adhoc"


@dataclass(frozen=True)
class _Audio:
    clips: dict[str, AudioClip]
    alignments: dict[str, Alignment]
    text_items: list[EvalItem]
    text_sha256: str


@dataclass(frozen=True)
class _Target:
    items: list[EvalItem]
    dataset: str
    reports: str  # the subdirectory of the reports directory
    set_name: str | None = None
    set_sha256: str | None = None
    audio: _Audio | None = None


class _MissingTranscripts(Exception):
    pass


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
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="for the audio set: transcribe each clip (cached by audio hash) and score it",
    )
    parser.add_argument("--profile", help="AWS profile, for --transcribe on uncached clips")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--bucket", help="evaluation clip bucket (default EVAL_AUDIO_BUCKET)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="price the run from the cache and exit: no model calls, nothing written",
    )
    cache_mode = parser.add_mutually_exclusive_group()
    cache_mode.add_argument("--no-cache", action="store_true", help="always call the model")
    cache_mode.add_argument(
        "--offline",
        action="store_true",
        help="answer only from the cache; fail before running if any item is missing",
    )
    return parser


def make_transcriber(profile: str | None, region: str, bucket: str | None) -> Transcribe:
    if not bucket:
        raise SetError("set EVAL_AUDIO_BUCKET or pass --bucket (stack output EvalAudioBucketName)")
    session = boto3.Session(profile_name=profile, region_name=region)
    return AwsClipTranscriber(session.client("transcribe"), session.client("s3"), bucket)


def _audio_target(args: argparse.Namespace) -> _Target:
    if not args.transcribe:
        raise SetError("the audio set is scored with --transcribe")
    clips = {clip.test_item_id: clip for clip in load_clips(args.sets_dir)}
    if not clips:
        raise SetError("the audio set has no clips yet (uv run eval-audio make)")
    items = source_items(args.sets_dir)
    cache = TranscriptCache(args.cache_dir / "transcripts")
    missing = [clip for clip in clips.values() if cache.get(clip.sha256) is None]
    if missing and (args.offline or args.estimate):
        raise _MissingTranscripts(f"{len(missing)} clips have no cached transcript")
    if missing:
        transcribe = make_transcriber(
            args.profile, args.region, args.bucket or Settings().eval_audio_bucket
        )
        for clip in missing:
            cache.put(clip.sha256, transcribe(clip))
    alignments = {}
    for item_id, clip in clips.items():
        turns = cache.get(clip.sha256)
        assert turns is not None
        alignments[item_id] = align(items[item_id], turns)
    manifest = load_manifest("audio", args.sets_dir)
    text_set = load_set(manifest.items_from or "test", args.sets_dir)
    return _Target(
        [alignments[item_id].item for item_id in sorted(alignments)],
        dataset="audio",
        reports="audio",
        set_name="audio",
        set_sha256=canonical_sha256(set_dir("audio", args.sets_dir) / "clips.jsonl"),
        audio=_Audio(
            clips=clips,
            alignments=alignments,
            text_items=[items[item_id] for item_id in sorted(alignments)],
            text_sha256=text_set.sha256,
        ),
    )


def _target(args: argparse.Namespace) -> _Target:
    if args.data is not None:
        if args.transcribe:
            raise SetError("--transcribe applies to the audio set only")
        return _Target(load_dataset(args.data), dataset=args.data.name, reports=ADHOC)
    if load_manifest(args.set_name or "dev", args.sets_dir).kind == "audio":
        return _audio_target(args)
    if args.transcribe:
        raise SetError("--transcribe applies to the audio set only")
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


def export_site_main(argv: list[str] | None = None) -> int:
    """`uv run eval-export-site`: write the /evals data under frontend/src/data/evals."""
    parser = argparse.ArgumentParser(
        prog="eval-export-site", description="Write the static data for the /evals pages."
    )
    parser.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--out", type=Path, default=SITE_DATA_DIR)
    args = parser.parse_args(argv)
    result = export_site(args.sets_dir, args.reports_dir, args.out)
    print(f"exported {result.runs} runs to {args.out}")
    for name in result.removed:
        print(f"  removed stale {name}")
    return 0


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
        if args.offline or args.estimate:
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
    except _MissingTranscripts as error:
        print(f"eval: {error}; run without --offline or --estimate to transcribe", file=sys.stderr)
        return 1
    except (BotoCoreError, ClientError, RuntimeError) as error:
        # AWS credentials, the bucket or a transcription job: transcripts done so far stay cached.
        print(f"eval: transcription failed: {error}", file=sys.stderr)
        return 1
    described = analyzer.describe()
    every_item = target.items + (target.audio.text_items if target.audio else [])
    if args.estimate:
        requests = [request_for(item) for item in every_item]
        estimate = estimate_run(requests, analyzer, ResponseCache(args.cache_dir))
        print("\n".join(render_estimate(estimate, described.prompt_version)))
        return 0
    if args.offline:
        first = analyzer.screen if isinstance(analyzer, TwoStageExtractor) else analyzer
        assert isinstance(first, CachedAnalyzer)
        missing = [i.id for i in every_item if not first.is_cached(request_for(i))]
        if missing:
            print(
                f"eval: --offline: {len(missing)} of {len(every_item)} items are not cached "
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
        text_results = (
            asyncio.run(run_items(target.audio.text_items, analyzer, concurrency=args.concurrency))
            if target.audio
            else []
        )
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
    if target.audio is not None:
        penalty = audio_scores(
            target.audio.clips,
            target.audio.alignments,
            results,
            text_results,
            text_sha256=target.audio.text_sha256,
        )
        transcripts = {item.id: item.turns for item in target.items}
        details = [
            detail.model_copy(update={"transcript": transcripts[detail.item_id]})
            for detail in report.items
        ]
        report = report.model_copy(update={"audio": penalty, "items": details})
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
