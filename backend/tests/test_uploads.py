"""Presigned S3 POSTs: signed locally by botocore, so these tests make no network calls."""

import base64
import json
from typing import Any

import boto3
import pytest

from commitment_tracker.jobs.audio import MAX_AUDIO_BYTES
from commitment_tracker.jobs.uploads import S3UploadSigner, UploadSigner

BUCKET = "audio-bucket"


def signer(ttl: int = 300, now: float = 1_761_000_000.5) -> S3UploadSigner:
    s3 = boto3.client(
        "s3",
        region_name="us-east-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    return S3UploadSigner(s3, BUCKET, expires_in=ttl, clock=lambda: now)


def policy_of(fields: dict[str, str]) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(base64.b64decode(fields["policy"]))
    return decoded


def test_it_satisfies_the_protocol() -> None:
    chosen: UploadSigner = signer()
    assert chosen.presign()


def test_the_key_is_uploads_slash_uuid_dot_wav() -> None:
    ticket = signer().presign()
    assert ticket.key == f"uploads/{ticket.upload_id}.wav"
    assert len(ticket.upload_id) == 32
    assert ticket.fields["key"] == ticket.key


def test_each_ticket_has_a_fresh_id() -> None:
    s = signer()
    assert s.presign().upload_id != s.presign().upload_id


def test_the_url_is_the_regional_bucket_endpoint() -> None:
    ticket = signer().presign()
    assert ticket.url.startswith("https://")
    assert BUCKET in ticket.url


def test_the_policy_caps_the_size_and_pins_key_and_type() -> None:
    ticket = signer().presign()
    conditions = policy_of(ticket.fields)["conditions"]
    assert ["content-length-range", 1, MAX_AUDIO_BYTES] in conditions
    assert ["eq", "$Content-Type", "audio/wav"] in conditions
    assert {"key": ticket.key} in conditions
    assert {"bucket": BUCKET} in conditions
    assert ticket.fields["Content-Type"] == "audio/wav"


def test_the_policy_expires_after_the_ttl() -> None:
    expiry = policy_of(signer(ttl=120).presign().fields)["expiration"]
    assert expiry.endswith("Z")


def test_it_carries_the_signature_fields_the_browser_must_echo() -> None:
    fields = signer().presign().fields
    assert {"policy", "x-amz-signature", "x-amz-credential"} <= set(fields)


@pytest.mark.parametrize("ttl", [0, -5])
def test_a_non_positive_ttl_is_rejected(ttl: int) -> None:
    with pytest.raises(ValueError, match="expires_in"):
        signer(ttl=ttl)


def test_the_presign_time_is_pinned_as_object_metadata() -> None:
    """The upload stage is timed from this value, so the client must not be able to change it."""
    ticket = signer().presign()
    assert ticket.fields["x-amz-meta-presigned-at"] == "1761000000500"
    assert ["eq", "$x-amz-meta-presigned-at", "1761000000500"] in policy_of(ticket.fields)[
        "conditions"
    ]
