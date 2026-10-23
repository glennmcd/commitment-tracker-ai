"""What feedback stores, and the store boundary.

A vote holds ids, the label the server copied from the job, the vote and a time: no text, no
address, no expiry. A content item (only with the visitor's consent) holds the transcript and the
spans copied from the job record, and expires after 90 days.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from commitment_tracker.schemas import Span, Turn

CONTENT_TTL_SECONDS = 90 * 86_400


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class VoteItem(_Item):
    job_id: str
    span_index: int
    label: str
    vote: Literal["up", "down"]
    feedback_id: str  # names the content item, when there is one
    voted_at: int  # epoch seconds


class ContentItem(_Item):
    feedback_id: str
    job_id: str
    transcript: list[Turn]
    spans: list[Span]
    expires_at: int  # epoch seconds, DynamoDB's TTL unit


class FeedbackStore(Protocol):
    def put_vote(self, vote: VoteItem) -> None:
        """Store the vote, replacing an earlier vote on the same span of the same job."""
        ...

    def put_content(self, item: ContentItem) -> None: ...

    def delete_content(self, feedback_id: str) -> None:
        """Remove a kept transcript; one that is already gone is not an error."""
        ...


class MemoryFeedbackStore:
    def __init__(self) -> None:
        self.votes: dict[tuple[str, int], VoteItem] = {}
        self.contents: dict[str, ContentItem] = {}

    def put_vote(self, vote: VoteItem) -> None:
        self.votes[(vote.job_id, vote.span_index)] = vote

    def put_content(self, item: ContentItem) -> None:
        self.contents[item.feedback_id] = item

    def delete_content(self, feedback_id: str) -> None:
        self.contents.pop(feedback_id, None)
