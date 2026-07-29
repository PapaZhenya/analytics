import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceCreate(BaseModel):
    utterance_id: uuid.UUID | None = None
    start_time: float
    end_time: float
    quote_text: str
    evidence_type: str = Field(pattern="^(violation|positive)$")


class ReviewActionRequest(BaseModel):
    action: str = Field(pattern="^(confirm|reject|correct|add_evidence|remove_evidence|reopen)$")
    new_verdict: str | None = Field(default=None, pattern="^(pass|fail|na)$")
    notes: str | None = None
    evidence: EvidenceCreate | None = None  # required for action=add_evidence
    evidence_id: uuid.UUID | None = None  # required for action=remove_evidence


class ReviewActionResponse(BaseModel):
    finding_id: uuid.UUID
    current_verdict: str
    human_corrected: bool


class ReviewActionHistoryItem(BaseModel):
    """One entry in a finding's immutable review-action log. Answers section 8's
    'whether a person changed it, who changed it and when' for every past action, not
    just the finding's current state."""
    id: uuid.UUID
    action_type: str
    previous_verdict: str | None
    new_verdict: str | None
    user_id: uuid.UUID
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
