"""Prove, against the deployed stack, that audio is deleted once it has been transcribed.

    uv run python scripts/check_audio_gone.py --api-url https://<api> --bucket <bucket> \
        --wav ../frontend/public/samples/<clip>.wav --profile <aws profile>

Uploads a clip the way the site does (presigned form, straight to S3), starts a job, waits for it
to finish, then asserts that the uploaded object, Transcribe's output object and the Transcribe job
are all gone. Exit status 0 means every one was; 1 means at least one was still there. The worker's
unit tests prove the same thing with fakes; this is the check on the real services. It needs AWS
credentials that may read the bucket's metadata and describe Transcribe jobs.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client
    from types_boto3_transcribe import TranscribeServiceClient

POLL_SECONDS = 1.0
MAX_POLLS = 150
_OBJECT_MISSING = {"404", "NoSuchKey", "NotFound"}
_JOB_MISSING = {"BadRequestException", "NotFoundException"}


class JobDidNotFinish(RuntimeError):
    pass


@dataclass(frozen=True)
class Report:
    job_id: str
    checks: list[tuple[str, bool]]  # (what was checked, True when it is gone)

    @property
    def ok(self) -> bool:
        return all(gone for _, gone in self.checks)


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def object_gone(s3: "S3Client", bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if _code(error) in _OBJECT_MISSING:
            return True
        raise
    return False


def transcribe_job_gone(transcribe: "TranscribeServiceClient", job_id: str) -> bool:
    try:
        transcribe.get_transcription_job(TranscriptionJobName=f"ct-{job_id}")
    except ClientError as error:
        if _code(error) in _JOB_MISSING:
            return True
        raise
    return False


def _upload(client: httpx.Client, wav: bytes) -> str:
    ticket = client.post("/uploads")
    ticket.raise_for_status()
    form: dict[str, Any] = ticket.json()
    stored = client.post(
        form["url"], data=form["fields"], files={"file": ("clip.wav", wav, "audio/wav")}
    )
    stored.raise_for_status()
    return str(form["upload_id"])


def check(
    client: httpx.Client,
    s3: "S3Client",
    transcribe: "TranscribeServiceClient",
    bucket: str,
    wav_path: Path,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_polls: int = MAX_POLLS,
) -> Report:
    upload_id = _upload(client, wav_path.read_bytes())
    started = client.post(
        "/jobs", json={"upload_id": upload_id, "call_date": date.today().isoformat()}
    )
    started.raise_for_status()
    job_id = str(started.json()["job_id"])

    for _ in range(max_polls):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] == "failed":
            raise JobDidNotFinish(f"the job failed ({job.get('error_code')}); nothing to check")
        if job["status"] == "done":
            break
        sleep(POLL_SECONDS)
    else:
        raise JobDidNotFinish("the job did not finish in time")

    return Report(
        job_id=job_id,
        checks=[
            ("upload object", object_gone(s3, bucket, f"uploads/{upload_id}.wav")),
            ("transcript output", object_gone(s3, bucket, f"transcripts/{job_id}.json")),
            ("Transcribe job", transcribe_job_gone(transcribe, job_id)),
        ],
    )


def format_report(report: Report) -> str:
    lines = [f"job {report.job_id}"]
    lines += [f"{'PASS' if gone else 'FAIL'}  {name}" for name, gone in report.checks]
    lines.append("audio is gone" if report.ok else "audio is NOT gone")
    return "\n".join(lines)


def report_json(report: Report) -> str:
    return json.dumps(
        {"job_id": report.job_id, "ok": report.ok, "checks": dict(report.checks)}, indent=2
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that uploaded audio is deleted after transcription."
    )
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--bucket", required=True, help="the audio bucket, from the stack output")
    parser.add_argument("--wav", type=Path, required=True, help="a 16 kHz mono WAV of at most 60 s")
    parser.add_argument("--profile", help="AWS profile of the project account")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    import boto3

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=60.0) as client:
        try:
            report = check(
                client, session.client("s3"), session.client("transcribe"), args.bucket, args.wav
            )
        except JobDidNotFinish as error:
            print(str(error), file=sys.stderr)
            return 2
    print(report_json(report) if args.json else format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
