"""Presigned S3 POSTs for browser uploads, so audio never passes through API Gateway.

The POST policy pins the object key and content type and caps the size at MAX_AUDIO_BYTES, which
is 60 s of the accepted WAV format. Signing happens locally in botocore; nothing here calls AWS.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from commitment_tracker.jobs.audio import MAX_AUDIO_BYTES

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

UPLOAD_PREFIX = "uploads"
CONTENT_TYPE = "audio/wav"


@dataclass(frozen=True)
class UploadTicket:
    upload_id: str
    key: str
    url: str
    fields: dict[str, str]
    expires_in: int


class UploadSigner(Protocol):
    def presign(self) -> UploadTicket: ...


class S3UploadSigner:
    def __init__(self, s3: "S3Client", bucket: str, *, expires_in: int = 300) -> None:
        if expires_in <= 0:
            raise ValueError("expires_in must be positive")
        self._s3 = s3
        self._bucket = bucket
        self._expires_in = expires_in

    def presign(self) -> UploadTicket:
        upload_id = uuid.uuid4().hex
        key = f"{UPLOAD_PREFIX}/{upload_id}.wav"
        post = self._s3.generate_presigned_post(
            self._bucket,
            key,
            Fields={"Content-Type": CONTENT_TYPE},
            Conditions=[
                ["content-length-range", 1, MAX_AUDIO_BYTES],
                ["eq", "$Content-Type", CONTENT_TYPE],
            ],
            ExpiresIn=self._expires_in,
        )
        logger.info("upload presigned upload_id=%s", upload_id)
        return UploadTicket(
            upload_id=upload_id,
            key=key,
            url=post["url"],
            fields=dict(post["fields"]),
            expires_in=self._expires_in,
        )
