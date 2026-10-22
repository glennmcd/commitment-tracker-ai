"""A job store on DynamoDB.

An item holds the key, the status and the expiry as attributes (conditions and the TTL need them)
and the whole record as one JSON string, which avoids DynamoDB's float and nesting rules.
DynamoDB deletes expired items late, so reads also check `expires_at`.
"""

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from commitment_tracker.jobs.record import JobRecord, JobStatus, JobUpdate

if TYPE_CHECKING:
    from types_boto3_dynamodb import DynamoDBClient

logger = logging.getLogger(__name__)


def _failed_condition(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


class DynamoJobStore:
    def __init__(
        self,
        client: "DynamoDBClient",
        table_name: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._table = table_name
        self._clock = clock

    def _item(self, job: JobRecord) -> dict[str, Any]:
        return {
            "id": {"S": job.id},
            "status": {"S": job.status.value},
            "expires_at": {"N": str(job.expires_at)},
            "record": {"S": job.model_dump_json()},
        }

    def _read(self, job_id: str) -> tuple[JobRecord, str] | None:
        """The stored record and its raw JSON, or None when absent or expired."""
        item = self._client.get_item(
            TableName=self._table, Key={"id": {"S": job_id}}, ConsistentRead=True
        ).get("Item")
        if item is None:
            return None
        raw = item["record"]["S"]
        job = JobRecord.model_validate_json(raw)
        return None if job.expires_at <= self._clock() else (job, raw)

    def create(self, job: JobRecord) -> JobRecord:
        try:
            self._client.put_item(
                TableName=self._table,
                Item=self._item(job),
                ConditionExpression="attribute_not_exists(id) OR expires_at <= :now",
                ExpressionAttributeValues={":now": {"N": str(int(self._clock()))}},
            )
        except ClientError as error:
            if not _failed_condition(error):
                raise
            found = self._read(job.id)
            if found is None:
                raise LookupError(f"job {job.id} expired while being created") from None
            logger.info("job already exists job_id=%s", job.id)
            return found[0]
        return job

    def get(self, job_id: str) -> JobRecord | None:
        found = self._read(job_id)
        return None if found is None else found[0]

    def transition(self, job_id: str, expected: JobStatus, update: JobUpdate) -> JobRecord | None:
        found = self._read(job_id)
        if found is None or found[0].status is not expected:
            return None
        current, raw = found
        updated = current.apply(update)
        try:
            self._client.put_item(
                TableName=self._table,
                Item=self._item(updated),
                ConditionExpression="#status = :expected AND #record = :previous",
                ExpressionAttributeNames={"#status": "status", "#record": "record"},
                ExpressionAttributeValues={
                    ":expected": {"S": expected.value},
                    ":previous": {"S": raw},
                },
            )
        except ClientError as error:
            if _failed_condition(error):
                return None
            raise
        return updated
