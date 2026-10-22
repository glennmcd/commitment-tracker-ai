"""scripts/check_audio_gone.py: the post-deploy proof that audio, output and job are deleted.

The API is a fake behind httpx's mock transport and AWS is botocore stubs: no network.
"""

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import boto3
import httpx
import pytest
from botocore.stub import Stubber

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_audio_gone.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_audio_gone", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_audio_gone"] = module
    spec.loader.exec_module(module)
    return module


script = load_script()
BUCKET = "audio-bucket"
UPLOAD_ID = "b" * 32
JOB = "a" * 64
S3_URL = "https://audio-bucket.s3.us-east-2.amazonaws.com/"


class Api:
    def __init__(self, *, final: str = "done") -> None:
        self.final = final
        self.requests: list[tuple[str, str]] = []
        self.s3_form: httpx.Request | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, str(request.url)))
        if request.url.host == "audio-bucket.s3.us-east-2.amazonaws.com":
            self.s3_form = request
            return httpx.Response(204)
        if request.url.path == "/uploads":
            ticket = {
                "upload_id": UPLOAD_ID,
                "url": S3_URL,
                "fields": {"key": f"uploads/{UPLOAD_ID}.wav", "policy": "p"},
                "max_bytes": 1_920_044,
                "expires_in": 300,
            }
            return httpx.Response(200, json=ticket)
        if request.method == "POST" and request.url.path == "/jobs":
            return httpx.Response(202, json={"job_id": JOB, "status": "transcribing"})
        if request.url.path == f"/jobs/{JOB}":
            return httpx.Response(
                200, json={"job_id": JOB, "status": self.final, "error_code": None}
            )
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url="http://api.test")


@pytest.fixture
def aws() -> Iterator[tuple[Any, Any, Stubber, Stubber]]:
    kwargs: dict[str, Any] = {
        "region_name": "us-east-2",
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
    }
    s3 = boto3.client("s3", **kwargs)
    transcribe = boto3.client("transcribe", **kwargs)
    with Stubber(s3) as s3_stub, Stubber(transcribe) as transcribe_stub:
        yield s3, transcribe, s3_stub, transcribe_stub


def wav_file(tmp_path: Path) -> Path:
    from tests.wav import make_wav

    path = tmp_path / "clip.wav"
    path.write_bytes(make_wav(2.0))
    return path


def expect_gone(s3_stub: Stubber, transcribe_stub: Stubber) -> None:
    s3_stub.add_client_error(
        "head_object", "404", expected_params={"Bucket": BUCKET, "Key": f"uploads/{UPLOAD_ID}.wav"}
    )
    s3_stub.add_client_error(
        "head_object", "404", expected_params={"Bucket": BUCKET, "Key": f"transcripts/{JOB}.json"}
    )
    transcribe_stub.add_client_error(
        "get_transcription_job",
        "BadRequestException",
        expected_params={"TranscriptionJobName": f"ct-{JOB}"},
    )


def run(
    api: Api, aws_clients: tuple[Any, Any, Stubber, Stubber], tmp_path: Path, **kwargs: Any
) -> Any:
    s3, transcribe, _, _ = aws_clients
    return script.check(
        api.client(), s3, transcribe, BUCKET, wav_file(tmp_path), sleep=lambda _: None, **kwargs
    )


# --- The check -----------------------------------------------------------------------------------


def test_everything_gone_passes(aws: tuple[Any, Any, Stubber, Stubber], tmp_path: Path) -> None:
    expect_gone(aws[2], aws[3])
    api = Api()

    report = run(api, aws, tmp_path)

    assert report.ok
    assert [name for name, _ in report.checks] == [
        "upload object",
        "transcript output",
        "Transcribe job",
    ]
    assert all(passed for _, passed in report.checks)
    aws[2].assert_no_pending_responses()
    aws[3].assert_no_pending_responses()


def test_the_clip_goes_to_s3_with_the_ticket_fields_first_and_the_file_last(
    aws: tuple[Any, Any, Stubber, Stubber], tmp_path: Path
) -> None:
    expect_gone(aws[2], aws[3])
    api = Api()

    run(api, aws, tmp_path)

    assert api.s3_form is not None
    body = api.s3_form.content
    assert body.index(b'name="key"') < body.index(b'name="policy"') < body.index(b'name="file"')


def test_an_object_that_is_still_there_fails(
    aws: tuple[Any, Any, Stubber, Stubber], tmp_path: Path
) -> None:
    s3_stub, transcribe_stub = aws[2], aws[3]
    s3_stub.add_response(
        "head_object", {}, {"Bucket": BUCKET, "Key": f"uploads/{UPLOAD_ID}.wav"}
    )  # still exists
    s3_stub.add_client_error("head_object", "404")
    transcribe_stub.add_client_error("get_transcription_job", "BadRequestException")

    report = run(Api(), aws, tmp_path)

    assert not report.ok
    assert dict(report.checks) == {
        "upload object": False,
        "transcript output": True,
        "Transcribe job": True,
    }


def test_a_transcribe_job_that_still_exists_fails(
    aws: tuple[Any, Any, Stubber, Stubber], tmp_path: Path
) -> None:
    s3_stub, transcribe_stub = aws[2], aws[3]
    s3_stub.add_client_error("head_object", "404")
    s3_stub.add_client_error("head_object", "404")
    transcribe_stub.add_response(
        "get_transcription_job",
        {
            "TranscriptionJob": {
                "TranscriptionJobName": f"ct-{JOB}",
                "TranscriptionJobStatus": "COMPLETED",
            }
        },
    )

    report = run(Api(), aws, tmp_path)

    assert not report.ok
    assert dict(report.checks)["Transcribe job"] is False


def test_other_aws_errors_are_not_mistaken_for_gone(
    aws: tuple[Any, Any, Stubber, Stubber], tmp_path: Path
) -> None:
    aws[2].add_client_error("head_object", "403")

    with pytest.raises(Exception, match="403"):
        run(Api(), aws, tmp_path)


def test_a_job_that_failed_is_reported_and_nothing_is_checked(
    aws: tuple[Any, Any, Stubber, Stubber], tmp_path: Path
) -> None:
    with pytest.raises(script.JobDidNotFinish, match="failed"):
        run(Api(final="failed"), aws, tmp_path)


def test_a_job_that_never_finishes_times_out(
    aws: tuple[Any, Any, Stubber, Stubber], tmp_path: Path
) -> None:
    with pytest.raises(script.JobDidNotFinish, match="did not finish"):
        run(Api(final="analyzing"), aws, tmp_path, max_polls=3)


def test_the_report_names_each_check() -> None:
    report = script.Report(job_id=JOB, checks=[("upload object", True), ("Transcribe job", False)])
    text = script.format_report(report)
    assert "PASS  upload object" in text
    assert "FAIL  Transcribe job" in text
    assert "audio is NOT gone" in text
    assert "audio is gone" in script.format_report(script.Report(job_id=JOB, checks=[("x", True)]))


def test_the_report_is_valid_json_when_asked() -> None:
    report = script.Report(job_id=JOB, checks=[("upload object", True)])
    assert json.loads(script.report_json(report)) == {
        "job_id": JOB,
        "ok": True,
        "checks": {"upload object": True},
    }
