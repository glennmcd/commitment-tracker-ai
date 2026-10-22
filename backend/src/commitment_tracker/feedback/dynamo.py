"""Feedback on DynamoDB: one table with a string key `pk` and TTL on `expires_at`.

Votes are `vote#<job_id>#<span_index>` and have no TTL. Content items are `content#<feedback_id>`;
the transcript and spans are one JSON string, which avoids DynamoDB's float and nesting rules.
"""

import logging
from typing import TYPE_CHECKING, Any

from commitment_tracker.feedback.store import ContentItem, VoteItem

if TYPE_CHECKING:
    from types_boto3_dynamodb import DynamoDBClient

logger = logging.getLogger(__name__)


def vote_to_item(vote: VoteItem) -> dict[str, Any]:
    return {
        "pk": {"S": f"vote#{vote.job_id}#{vote.span_index}"},
        "job_id": {"S": vote.job_id},
        "span_index": {"N": str(vote.span_index)},
        "label": {"S": vote.label},
        "vote": {"S": vote.vote},
        "feedback_id": {"S": vote.feedback_id},
        "voted_at": {"N": str(vote.voted_at)},
    }


def content_to_item(item: ContentItem) -> dict[str, Any]:
    record = item.model_dump_json(include={"transcript", "spans"})
    return {
        "pk": {"S": f"content#{item.feedback_id}"},
        "feedback_id": {"S": item.feedback_id},
        "job_id": {"S": item.job_id},
        "record": {"S": record},
        "expires_at": {"N": str(item.expires_at)},
    }


class DynamoFeedbackStore:
    def __init__(self, client: "DynamoDBClient", table_name: str) -> None:
        self._client = client
        self._table = table_name

    def put_vote(self, vote: VoteItem) -> None:
        self._client.put_item(TableName=self._table, Item=vote_to_item(vote))

    def put_content(self, item: ContentItem) -> None:
        self._client.put_item(TableName=self._table, Item=content_to_item(item))

    def delete_content(self, feedback_id: str) -> None:
        self._client.delete_item(TableName=self._table, Key={"pk": {"S": f"content#{feedback_id}"}})
