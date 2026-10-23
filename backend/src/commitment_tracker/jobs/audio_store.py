"""Reading and deleting uploaded audio in S3.

`read` returns the object's bytes and the time the upload was presigned (pinned in the POST policy
as object metadata, so the browser can't change it). It refuses an object over the size cap before
reading it.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from botocore.exceptions import ClientError

from commitment_tracker.jobs.audio import MAX_AUDIO_BYTES, AudioTooLong
from commitment_tracker.jobs.uploads import PRESIGNED_AT_METADATA

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredAudio:
    data: bytes
    uploaded_at_ms: int | None  # when the upload was presigned; None when unknown


class AudioStore(Protocol):
    @property
    def bucket(self) -> str: ...

    def read(self, key: str) -> StoredAudio | None:
        """The object, or None when it doesn't exist. Raises AudioTooLong over the size cap."""
        ...

    def delete(self, key: str) -> None: ...


def _presigned_at(metadata: dict[str, str]) -> int | None:
    raw = metadata.get(PRESIGNED_AT_METADATA, "")
    return int(raw) if raw.isdigit() else None


class S3AudioStore:
    def __init__(self, s3: "S3Client", bucket: str) -> None:
        self._s3 = s3
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    def read(self, key: str) -> StoredAudio | None:
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "NoSuchKey":
                return None
            raise
        body = response["Body"]
        if response["ContentLength"] > MAX_AUDIO_BYTES:
            body.close()
            raise AudioTooLong("the object is larger than the upload cap")
        data = body.read()
        return StoredAudio(data=data, uploaded_at_ms=_presigned_at(response.get("Metadata", {})))

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=key)
        logger.info("audio deleted key=%s", key)
