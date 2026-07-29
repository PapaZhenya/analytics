import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPKMixin, pg_enum


class CallSource(str, enum.Enum):
    upload = "upload"
    voiso = "voiso"
    asterisk = "asterisk"
    sftp = "sftp"
    api = "api"
    csv_import = "csv_import"


class CallStatus(str, enum.Enum):
    uploaded = "uploaded"
    queued = "queued"
    preprocessing = "preprocessing"
    diarizing = "diarizing"
    transcribing = "transcribing"
    aligning = "aligning"
    assigning_speakers = "assigning_speakers"
    analyzing = "analyzing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class StepStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class Sentiment(str, enum.Enum):
    Neutral = "Neutral"
    Positive = "Positive"
    Negative = "Negative"


class AudioVariant(str, enum.Enum):
    original = "original"
    enhanced = "enhanced"
    vocals = "vocals"


class SpeakerRole(Base, UUIDPKMixin):
    """Extensible speaker-role taxonomy — replaces the legacy binary Customer/CSR CHECK."""

    __tablename__ = "speaker_roles"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)


class Call(Base, UUIDPKMixin):
    __tablename__ = "calls"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    source: Mapped[CallSource] = mapped_column(
        pg_enum(CallSource, "call_source"), default=CallSource.upload, nullable=False
    )
    external_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    duration_seconds: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(10), nullable=True)

    status: Mapped[CallStatus] = mapped_column(
        pg_enum(CallStatus, "call_status"), default=CallStatus.uploaded, nullable=False
    )

    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    speakers: Mapped[list["Speaker"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    processing_steps: Mapped[list["CallProcessingStep"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )


class CallTag(Base, UUIDPKMixin):
    __tablename__ = "call_tags"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)


class CallFlag(Base, UUIDPKMixin):
    __tablename__ = "call_flags"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    flag_type: Mapped[str] = mapped_column(String(100), nullable=False)
    raised_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CallProcessingStep(Base, UUIDPKMixin):
    """One row per pipeline step (of the 18 in backend/pipeline/orchestrator.py).

    Upserted idempotently on (call_id, step_name) so a worker crash/restart can resume
    from the last succeeded step instead of reprocessing the whole call.
    """

    __tablename__ = "call_processing_steps"
    __table_args__ = (
        UniqueConstraint("call_id", "step_name", name="uq_call_processing_step"),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[StepStatus] = mapped_column(
        pg_enum(StepStatus, "step_status"), default=StepStatus.pending, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    call: Mapped["Call"] = relationship(back_populates="processing_steps")


class ProcessingJob(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "processing_jobs"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    celery_task_id: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Speaker(Base, UUIDPKMixin):
    __tablename__ = "speakers"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    diarization_label: Mapped[str] = mapped_column(String(50), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("speaker_roles.id"), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    call: Mapped["Call"] = relationship(back_populates="speakers")
    role: Mapped["SpeakerRole"] = relationship(lazy="joined")


class Utterance(Base, UUIDPKMixin):
    __tablename__ = "utterances"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    speaker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("speakers.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Numeric, nullable=False)
    end_time: Mapped[float] = mapped_column(Numeric, nullable=False)
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[Sentiment | None] = mapped_column(
        pg_enum(Sentiment, "sentiment"), nullable=True
    )
    is_profane: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    corrections: Mapped[list["UtteranceCorrection"]] = relationship(
        back_populates="utterance", cascade="all, delete-orphan", order_by="UtteranceCorrection.created_at"
    )


class UtteranceCorrection(Base, UUIDPKMixin):
    """Append-only revision log. Current text/speaker = latest row here, else the original."""

    __tablename__ = "utterance_corrections"

    utterance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utterances.id"), nullable=False)
    corrected_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("speakers.id"), nullable=True
    )
    corrected_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    utterance: Mapped["Utterance"] = relationship(back_populates="corrections")


class AcousticMetrics(Base, UUIDPKMixin):
    __tablename__ = "acoustic_metrics"

    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calls.id"), unique=True, nullable=False
    )
    source_audio_variant: Mapped[AudioVariant] = mapped_column(
        pg_enum(AudioVariant, "audio_variant"), default=AudioVariant.original, nullable=False
    )
    rms_loudness: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    zero_crossing_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    spectral_centroid: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    eq_20_250: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    eq_250_2000: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    eq_2000_6000: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    eq_6000_20000: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_1: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_2: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_3: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_4: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_5: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_6: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_7: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_8: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_9: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_10: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_11: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_12: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mfcc_13: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    silence_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    interruption_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_talk_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class CallSummary(Base, UUIDPKMixin):
    __tablename__ = "call_summaries"

    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calls.id"), unique=True, nullable=False
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    conflict_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics: Mapped[dict] = mapped_column(JSONB, default=dict)
