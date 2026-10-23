"""S3AudioStore against a botocore-stubbed client: no network, exact request parameters."""

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from commitment_tracker.jobs.audio import MAX_AUDIO_BYTES, AudioTooLong
from commitment_tracker.jobs.audio_store import AudioStore, S3AudioStore
from tests.fakes import FakeAudioStore

BUCKET = "audio-bucket"
KEY = "uploads/abc.wav"


class Rig:
    def __init__(self) -> None:
        self.s3 = boto3.client(
            "s3",
            region_name="us-east-2",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        self.stub = Stubber(self.s3)
        self.store = S3AudioStore(self.s3, BUCKET)


@pytest.fixture
def rig() -> Iterator[Rig]:
    rig = Rig()
    with rig.stub:
        yield rig
        rig.stub.assert_no_pending_responses()


def found(data: bytes, metadata: dict[str, str], length: int | None = None) -> dict[str, Any]:
    return {
        "Body": io.BytesIO(data),
        "ContentLength": len(data) if length is None else length,
        "Metadata": metadata,
        "LastModified": datetime(2026, 10, 22, tzinfo=UTC),
    }


def test_both_stores_satisfy_the_protocol() -> None:
    stores: list[AudioStore] = [FakeAudioStore(), Rig().store]
    assert [s.bucket for s in stores] == [BUCKET, BUCKET]


def test_read_returns_the_bytes_and_the_presign_time(rig: Rig) -> None:
    rig.stub.add_response(
        "get_object",
        found(b"RIFF", {"presigned-at": "1761000000123"}),
        {"Bucket": BUCKET, "Key": KEY},
    )
    audio = rig.store.read(KEY)
    assert audio is not None
    assert audio.data == b"RIFF"
    assert audio.uploaded_at_ms == 1761000000123


@pytest.mark.parametrize("metadata", [{}, {"presigned-at": "soon"}, {"presigned-at": "-4"}])
def test_a_missing_or_bad_presign_time_is_none(rig: Rig, metadata: dict[str, str]) -> None:
    rig.stub.add_response("get_object", found(b"RIFF", metadata), {"Bucket": BUCKET, "Key": KEY})
    audio = rig.store.read(KEY)
    assert audio is not None
    assert audio.uploaded_at_ms is None


def test_a_missing_object_is_none(rig: Rig) -> None:
    rig.stub.add_client_error(
        "get_object", "NoSuchKey", expected_params={"Bucket": BUCKET, "Key": KEY}
    )
    assert rig.store.read(KEY) is None


def test_an_object_over_the_cap_is_too_long_and_is_not_read(rig: Rig) -> None:
    rig.stub.add_response(
        "get_object",
        found(b"x", {}, length=MAX_AUDIO_BYTES + 1),
        {"Bucket": BUCKET, "Key": KEY},
    )
    with pytest.raises(AudioTooLong):
        rig.store.read(KEY)


def test_other_errors_propagate(rig: Rig) -> None:
    rig.stub.add_client_error(
        "get_object", "AccessDenied", expected_params={"Bucket": BUCKET, "Key": KEY}
    )
    with pytest.raises(Exception, match="AccessDenied"):
        rig.store.read(KEY)


def test_delete_removes_the_object(rig: Rig) -> None:
    rig.stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": KEY})
    rig.store.delete(KEY)
