import uuid

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
