"""Amazon Transcribe batch jobs through boto3: audio in our bucket, JSON output back in it.

Jobs are named `ct-<job_id>` (the EventBridge rule matches that prefix) and write their output to
`transcripts/<job_id>.json` in our bucket, not the service-managed location. Nothing here logs
transcript text.
"""

import json
import logging
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from commitment_tracker.transcription.protocol import AudioRef, TimedTurn
from commitment_tracker.transcription.turns import TranscriptFormatError, to_timed_turns

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client
    from types_boto3_transcribe import TranscribeServiceClient

logger = logging.getLogger(__name__)

SAMPLE_RATE_HZ = 16_000
MAX_SPEAKERS = 2
# Documented codes for "no such job" vary by action; both mean there is nothing left to delete.
_JOB_GONE = {"BadRequestException", "NotFoundException"}


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


class AwsBatchTranscriber:
    def __init__(
        self,
        transcribe: "TranscribeServiceClient",
        s3: "S3Client",
        bucket: str,
        prefix: str = "transcripts",
    ) -> None:
        self._transcribe = transcribe
        self._s3 = s3
        self._bucket = bucket
        self._prefix = prefix

    def _output_key(self, job_id: str) -> str:
        return f"{self._prefix}/{job_id}.json"

    def start(self, audio: AudioRef, job_id: str) -> None:
        try:
            self._transcribe.start_transcription_job(
                TranscriptionJobName=f"ct-{job_id}",
                LanguageCode="en-US",
                MediaFormat="wav",
                MediaSampleRateHertz=SAMPLE_RATE_HZ,
                Media={"MediaFileUri": audio.uri},
                OutputBucketName=self._bucket,
                OutputKey=self._output_key(job_id),
                Settings={"ShowSpeakerLabels": True, "MaxSpeakerLabels": MAX_SPEAKERS},
            )
        except ClientError as error:
            if _code(error) != "ConflictException":
                raise
            logger.info("transcription job already exists job_id=%s", job_id)
            return
        logger.info("transcription started job_id=%s", job_id)

    def result(self, job_id: str) -> list[TimedTurn]:
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=self._output_key(job_id))
        except ClientError as error:
            if _code(error) == "NoSuchKey":
                raise LookupError(f"no transcript output for job {job_id}") from None
            raise
        try:
            output = json.loads(response["Body"].read())
        except ValueError:
            raise TranscriptFormatError("Transcribe output is not valid JSON") from None
        turns = to_timed_turns(output)
        logger.info("transcript read job_id=%s turns=%d", job_id, len(turns))
        return turns

    def delete(self, job_id: str) -> None:
        """Remove the output object and the Transcribe job; already-gone is not an error."""
        self._s3.delete_object(Bucket=self._bucket, Key=self._output_key(job_id))
        try:
            self._transcribe.delete_transcription_job(TranscriptionJobName=f"ct-{job_id}")
        except ClientError as error:
            if _code(error) not in _JOB_GONE:
                raise
        logger.info("transcription deleted job_id=%s", job_id)
