"""The shape the model must return, sent to the API as the structured-output schema.

It differs from `schemas.Span`: the model gives only the raw due phrase and a precision hint (code
resolves dates), and there are no ledger flags. Every field is required; optional values are
nullable instead, because structured outputs limit optional parameters per request.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from commitment_tracker.schemas import Label, Precision


class ModelContract(BaseModel):
    # Errors are sent back to the model on retry and may be logged: never include input values.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ModelDue(ModelContract):
    raw: str | None = Field(
        description="The due phrase exactly as spoken, e.g. 'by Friday'; null if none."
    )
    precision_hint: Precision = Field(
        description="day, week, event (tied to an event), vague, or none when raw is null."
    )


class ModelSpan(ModelContract):
    turn_index: int = Field(ge=0, description="Index of the turn the quote is copied from.")
    label: Label
    owner: str | None = Field(description="Who is bound to act: a speaker id or a named person.")
    recipient: str | None = Field(description="Who the action is for, if stated or implied.")
    action: str | None = Field(description="Short verb phrase, e.g. 'send revised pricing'.")
    due: ModelDue
    condition: str | None = Field(description="The stated condition; required for CONDITIONAL.")
    confidence: float = Field(ge=0, le=1, description="Confidence in the label, from 0 to 1.")
    quote: str = Field(description="Exact text copied from the turn, character for character.")
    rationale: str = Field(description="A one-sentence explanation of why this label fits.")
    ambiguous: bool = Field(description="True for sarcasm or genuinely ambiguous statements.")

    @field_validator("label", mode="before")
    @classmethod
    def _label_case(cls, value: object) -> object:
        # Structured outputs may change enum capitalisation ("Commitment") without an error.
        return value.strip().upper() if isinstance(value, str) else value


class ModelOutput(ModelContract):
    spans: list[ModelSpan]
