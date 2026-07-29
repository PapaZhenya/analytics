"""Every rule evaluator must return a CriterionResult, and it is validated by Pydantic
before ever reaching qa_findings/qa_finding_evidence. An evaluator that raises, returns
the wrong shape, or produces free-form prose instead of this schema never gets persisted
as a QA result — this is what makes the engine "schema-validated, not one prompt"."""
import uuid

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    utterance_id: uuid.UUID | None = None
    start_time: float
    end_time: float
    quote_text: str
    evidence_type: str = Field(pattern="^(violation|positive)$")


class CriterionResult(BaseModel):
    criterion_id: uuid.UUID
    verdict: str = Field(pattern="^(pass|fail|na)$")
    explanation: str
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    engine_version: str
    human_modified: bool = False
