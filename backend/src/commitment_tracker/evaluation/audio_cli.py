"""`uv run eval-audio make|add|upload|fetch`: the evaluation clips and their bucket."""

import argparse
import sys
from pathlib import Path

import boto3

from commitment_tracker.evaluation.audio import (
    AUDIO_DIR,
    DEFAULT_VOICES,
    AudioSetError,
    ClipStore,
    S3ClipStore,
    add_human,
    fetch,
    make_polly,
    parse_readers,
    upload,
)
from commitment_tracker.evaluation.sets import SETS_DIR, SetError
from commitment_tracker.evaluation.synthesis import Synthesizer, polly_synthesizer
from commitment_tracker.settings import Settings


def make_synthesizer(profile: str | None, region: str) -> Synthesizer:
    session = boto3.Session(profile_name=profile, region_name=region)
    return polly_synthesizer(session.client("polly"))


def make_clip_store(profile: str | None, region: str, bucket: str) -> ClipStore:
    session = boto3.Session(profile_name=profile, region_name=region)
    return S3ClipStore(session.client("s3"), bucket)


def audio_main(argv: list[str] | None = None) -> int:
    """`uv run eval-audio make|add|upload|fetch`: the evaluation clips and their bucket."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sets-dir", type=Path, default=SETS_DIR)
    common.add_argument("--audio-dir", type=Path, default=AUDIO_DIR)
    common.add_argument("--profile", help="AWS profile of the project account")
    common.add_argument("--region", default="us-east-2")
    common.add_argument("--bucket", help="default: EVAL_AUDIO_BUCKET (stack output)")
    parser = argparse.ArgumentParser(prog="eval-audio", description="Manage evaluation clips.")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("make", parents=[common], help="speak items with Polly")
    make.add_argument("--item", action="append", required=True, help="a test item id")
    make.add_argument("--voices", default=",".join(DEFAULT_VOICES), help="two Polly voices")
    add = commands.add_parser("add", parents=[common], help="pin a human recording")
    add.add_argument("item")
    add.add_argument("wav", type=Path)
    add.add_argument("--readers", required=True, help="e.g. seller=reader-1,buyer=reader-2")
    commands.add_parser("upload", parents=[common], help="push local clips to the bucket")
    commands.add_parser("fetch", parents=[common], help="download clips, checking hashes")
    args = parser.parse_args(argv)

    try:
        if args.command == "make":
            first, second = args.voices.split(",")
            synthesize = make_synthesizer(args.profile, args.region)
            made = make_polly(
                args.item, args.sets_dir, args.audio_dir, synthesize, voices=(first, second)
            )
            for clip in made:
                print(f"{clip.test_item_id}: polly, {clip.duration_ms / 1000:.1f} s")
            return 0
        if args.command == "add":
            readers = parse_readers(args.readers)
            clip = add_human(args.item, args.wav, readers, args.sets_dir, args.audio_dir)
            print(f"{clip.test_item_id}: human, {clip.duration_ms / 1000:.1f} s")
            return 0
        bucket = args.bucket or Settings().eval_audio_bucket
        if not bucket:
            print(
                "eval-audio: set EVAL_AUDIO_BUCKET or pass --bucket (stack output "
                "EvalAudioBucketName)",
                file=sys.stderr,
            )
            return 2
        store = make_clip_store(args.profile, args.region, bucket)
        moved = (upload if args.command == "upload" else fetch)(
            args.sets_dir, args.audio_dir, store
        )
        print(f"{args.command}: {len(moved)} clips ({', '.join(moved) or 'none needed'})")
        return 0
    except (AudioSetError, SetError, ValueError) as error:
        print(f"eval-audio: {error}", file=sys.stderr)
        return 1
