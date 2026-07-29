import uuid
from datetime import datetime

from pydantic import BaseModel

from backend.app.models.calls import CallSource, CallStatus, Sentiment


class CallListItem(BaseModel):
    id: uuid.UUID
    original_filename: str
    status: CallStatus
    source: CallSource
    agent_id: uuid.UUID | None
    project_id: uuid.UUID
    detected_language: str | None
    duration_seconds: float | None
    uploaded_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class CallListResponse(BaseModel):
    items: list[CallListItem]
    total: int
    page: int
    page_size: int


class ProcessingStepOut(BaseModel):
    step_name: str
    sequence: int
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None

    model_config = {"from_attributes": True}


class CallStatusResponse(BaseModel):
    call_id: uuid.UUID
    status: CallStatus
    steps: list[ProcessingStepOut]
    percent_complete: int


class SpeakerOut(BaseModel):
    id: uuid.UUID
    diarization_label: str
    role_code: str
    display_name: str | None

    model_config = {"from_attributes": True}


class UtteranceOut(BaseModel):
    id: uuid.UUID
    speaker_id: uuid.UUID
    sequence: int
    start_time: float
    end_time: float
    content: str
    original_content: str
    is_corrected: bool
    sentiment: Sentiment | None
    is_profane: bool

    model_config = {"from_attributes": True}


class EvidenceOut(BaseModel):
    id: uuid.UUID
    utterance_id: uuid.UUID | None
    start_time: float
    end_time: float
    quote_text: str
    evidence_type: str
    added_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class FindingOut(BaseModel):
    id: uuid.UUID
    criterion_id: uuid.UUID
    criterion_code: str
    criterion_text: str
    ai_verdict: str
    ai_confidence: float | None
    ai_explanation: str | None
    current_verdict: str
    human_corrected: bool
    reviewed_by: uuid.UUID | None
    notes: str | None
    evidence: list[EvidenceOut]

    model_config = {"from_attributes": True}


class QAEvaluationOut(BaseModel):
    id: uuid.UUID
    scorecard_id: uuid.UUID
    overall_score: float | None
    max_score: float | None
    status: str
    findings: list[FindingOut]

    model_config = {"from_attributes": True}


class CommentOut(BaseModel):
    id: uuid.UUID
    utterance_id: uuid.UUID | None
    user_id: uuid.UUID
    body: str
    parent_comment_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CallDetailResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    status: CallStatus
    source: CallSource
    detected_language: str | None
    duration_seconds: float | None
    uploaded_at: datetime
    processed_at: datetime | None
    speakers: list[SpeakerOut]
    utterances: list[UtteranceOut]
    evaluations: list[QAEvaluationOut]
    comments: list[CommentOut]
    tags: list[str]


class UtteranceCorrectionRequest(BaseModel):
    corrected_content: str | None = None
    corrected_speaker_id: uuid.UUID | None = None
    reason: str | None = None


class UtteranceCorrectionResponse(BaseModel):
    utterance_id: uuid.UUID
    content: str
    speaker_id: uuid.UUID
    is_corrected: bool
