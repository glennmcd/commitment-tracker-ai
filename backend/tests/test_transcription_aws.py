"""AwsBatchTranscriber against botocore-stubbed clients: no network, exact request parameters."""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from commitment_tracker.transcription.aws import AwsBatchTranscriber
from commitment_tracker.transcription.fake import FakeTranscriber
from commitment_tracker.transcription.protocol import AudioRef, Transcriber
from commitment_tracker.transcription.turns import TranscriptFormatError, to_timed_turns

FIXTURE = Path(__file__).parent / "fixtures" / "transcribe-output.json"
BUCKET = "audio-bucket"
AUDIO = AudioRef(bucket=BUCKET, key="uploads/abc.wav")
OUTPUT_KEY = "transcripts/abc.json"


class Rig:
    def __init__(self) -> None:
        kwargs: dict[str, Any] = {
            "region_name": "us-east-2",
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        }
        self.transcribe = boto3.client("transcribe", **kwargs)
        self.s3 = boto3.client("s3", **kwargs)
        self.transcribe_stub = Stubber(self.transcribe)
        self.s3_stub = Stubber(self.s3)
        self.transcriber = AwsBatchTranscriber(self.transcribe, self.s3, BUCKET)


@pytest.fixture
def rig() -> Iterator[Rig]:
    rig = Rig()
    with rig.transcribe_stub, rig.s3_stub:
        yield rig
        rig.transcribe_stub.assert_no_pending_responses()
        rig.s3_stub.assert_no_pending_responses()


def body(data: bytes) -> dict[str, Any]:
    return {"Body": io.BytesIO(data)}


def test_satisfies_the_protocol(rig: Rig) -> None:
    transcriber: Transcriber = rig.transcriber
    assert isinstance(transcriber, AwsBatchTranscriber)


def test_start_submits_a_labelled_batch_job(rig: Rig) -> None:
    rig.transcribe_stub.add_response(
        "start_transcription_job",
        {"TranscriptionJob": {"TranscriptionJobName": "ct-abc"}},
        {
            "TranscriptionJobName": "ct-abc",
            "LanguageCode": "en-US",
            "MediaFormat": "wav",
            "MediaSampleRateHertz": 16000,
            "Media": {"MediaFileUri": "s3://audio-bucket/uploads/abc.wav"},
            "OutputBucketName": BUCKET,
            "OutputKey": OUTPUT_KEY,
            "Settings": {"ShowSpeakerLabels": True, "MaxSpeakerLabels": 2},
        },
    )

    rig.transcriber.start(AUDIO, "abc")


def test_start_treats_an_existing_job_as_started(rig: Rig) -> None:
    rig.transcribe_stub.add_client_error("start_transcription_job", "ConflictException")

    rig.transcriber.start(AUDIO, "abc")


def test_start_raises_other_errors(rig: Rig) -> None:
    rig.transcribe_stub.add_client_error("start_transcription_job", "LimitExceededException")

    with pytest.raises(Exception, match="LimitExceededException"):
        rig.transcriber.start(AUDIO, "abc")


def test_result_maps_the_stored_output(rig: Rig) -> None:
    raw = FIXTURE.read_bytes()
    rig.s3_stub.add_response("get_object", body(raw), {"Bucket": BUCKET, "Key": OUTPUT_KEY})

    turns = rig.transcriber.result("abc")

    assert turns == to_timed_turns(json.loads(raw))
    assert len(turns) == 11


def test_result_for_a_missing_output_raises_lookup_error(rig: Rig) -> None:
    rig.s3_stub.add_client_error("get_object", "NoSuchKey")

    with pytest.raises(LookupError):
        rig.transcriber.result("abc")


def test_result_rejects_malformed_json(rig: Rig) -> None:
    rig.s3_stub.add_response("get_object", body(b"not json"))

    with pytest.raises(TranscriptFormatError):
        rig.transcriber.result("abc")


def test_result_rejects_unexpected_shape(rig: Rig) -> None:
    rig.s3_stub.add_response("get_object", body(b'{"results": {}}'))

    with pytest.raises(TranscriptFormatError):
        rig.transcriber.result("abc")


def test_delete_removes_the_output_and_the_job(rig: Rig) -> None:
    rig.s3_stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": OUTPUT_KEY})
    rig.transcribe_stub.add_response(
        "delete_transcription_job", {}, {"TranscriptionJobName": "ct-abc"}
    )

    rig.transcriber.delete("abc")


@pytest.mark.parametrize("code", ["BadRequestException", "NotFoundException"])
def test_delete_ignores_a_job_that_is_already_gone(rig: Rig, code: str) -> None:
    rig.s3_stub.add_response("delete_object", {})
    rig.transcribe_stub.add_client_error("delete_transcription_job", code)

    rig.transcriber.delete("abc")


def test_delete_raises_other_job_errors(rig: Rig) -> None:
    rig.s3_stub.add_response("delete_object", {})
    rig.transcribe_stub.add_client_error("delete_transcription_job", "InternalFailureException")

    with pytest.raises(Exception, match="InternalFailureException"):
        rig.transcriber.delete("abc")


def test_delete_raises_output_errors_before_touching_the_job(rig: Rig) -> None:
    rig.s3_stub.add_client_error("delete_object", "InternalError")

    with pytest.raises(Exception, match="InternalError"):
        rig.transcriber.delete("abc")


def test_fake_records_deletes() -> None:
    fake = FakeTranscriber()

    fake.delete("abc")

    assert fake.deleted == ["abc"]
