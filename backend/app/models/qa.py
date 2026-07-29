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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPKMixin, pg_enum


class RuleType(str, enum.Enum):
    keyword = "keyword"
    regex = "regex"
    sequence = "sequence"
    timing = "timing"
    silence_interruption = "silence_interruption"
    speaker_behavior = "speaker_behavior"
    script_compliance = "script_compliance"
    semantic = "semantic"
    hybrid = "hybrid"
    manual_only = "manual_only"


class SpeakerScope(str, enum.Enum):
    agent = "agent"
    client = "client"
    any = "any"


class ScoringLogic(str, enum.Enum):
    pass_fail = "pass_fail"
    numeric = "numeric"
    weighted = "weighted"


class EvaluationMode(str, enum.Enum):
    automatic = "automatic"
    ai_assisted = "ai_assisted"
    manual_only = "manual_only"


class Verdict(str, enum.Enum):
    pass_ = "pass"
    fail = "fail"
    na = "na"


class EvaluationStatus(str, enum.Enum):
    pending_review = "pending_review"
    reviewed = "reviewed"


class EvidenceType(str, enum.Enum):
    violation = "violation"
    positive = "positive"


class ReviewActionType(str, enum.Enum):
    confirm = "confirm"
    reject = "reject"
    correct = "correct"
    add_evidence = "add_evidence"
    remove_evidence = "remove_evidence"
    reopen = "reopen"


class Scorecard(Base, UUIDPKMixin, TimestampMixin):
    """Versioned scorecard. A published version (published_at set) is immutable —
    edits create a new row sharing the same group_id with version+1, so historical
    qa_evaluations always point at the exact version used and never silently change.
    """

    __tablename__ = "scorecards"

    group_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    sections: Mapped[list["ScorecardSection"]] = relationship(
        back_populates="scorecard", cascade="all, delete-orphan", order_by="ScorecardSection.order_index"
    )

    @property
    def is_published(self) -> bool:
        return self.published_at is not None


class ScorecardSection(Base, UUIDPKMixin):
    __tablename__ = "scorecard_sections"

    scorecard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scorecards.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weight: Mapped[float] = mapped_column(Numeric, default=1, nullable=False)

    scorecard: Mapped["Scorecard"] = relationship(back_populates="sections")
    criteria: Mapped[list["ScorecardCriterion"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="ScorecardCriterion.order_index"
    )


class ScorecardCriterion(Base, UUIDPKMixin):
    __tablename__ = "scorecard_criteria"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scorecard_sections.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[RuleType] = mapped_column(pg_enum(RuleType, "rule_type"), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric, default=1, nullable=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_evidence: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    threshold: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    keywords: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    semantic_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker_scope: Mapped[SpeakerScope] = mapped_column(
        pg_enum(SpeakerScope, "speaker_scope"), default=SpeakerScope.any, nullable=False
    )
    timing_scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scoring_logic: Mapped[ScoringLogic] = mapped_column(
        pg_enum(ScoringLogic, "scoring_logic"), default=ScoringLogic.pass_fail, nullable=False
    )
    evaluation_mode: Mapped[EvaluationMode] = mapped_column(
        pg_enum(EvaluationMode, "evaluation_mode"), default=EvaluationMode.automatic, nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    section: Mapped["ScorecardSection"] = relationship(back_populates="criteria")


class QAEvaluation(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "qa_evaluations"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    scorecard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scorecards.id"), nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    status: Mapped[EvaluationStatus] = mapped_column(
        pg_enum(EvaluationStatus, "evaluation_status"),
        default=EvaluationStatus.pending_review,
        nullable=False,
    )

    findings: Mapped[list["QAFinding"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )
    # lazy="joined": every historical report needs the scorecard's version/name (section
    # 8: "scorecard version" must stay explainable), so this is always wanted, not an
    # occasional lookup worth deferring.
    scorecard: Mapped["Scorecard"] = relationship(lazy="joined")


class QAFinding(Base, UUIDPKMixin):
    __tablename__ = "qa_findings"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("qa_evaluations.id"), nullable=False
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scorecard_criteria.id"), nullable=False
    )
    ai_verdict: Mapped[Verdict] = mapped_column(pg_enum(Verdict, "verdict"), nullable=False)
    ai_confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(50), nullable=False)
    current_verdict: Mapped[Verdict] = mapped_column(pg_enum(Verdict, "verdict"), nullable=False)
    human_corrected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    evaluation: Mapped["QAEvaluation"] = relationship(back_populates="findings")
    criterion: Mapped["ScorecardCriterion"] = relationship(lazy="joined")
    evidence: Mapped[list["QAFindingEvidence"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )
    review_actions: Mapped[list["ReviewAction"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="ReviewAction.created_at"
    )


class QAFindingEvidence(Base, UUIDPKMixin):
    __tablename__ = "qa_finding_evidence"

    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qa_findings.id"), nullable=False)
    utterance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("utterances.id"), nullable=True
    )
    start_time: Mapped[float] = mapped_column(Numeric, nullable=False)
    end_time: Mapped[float] = mapped_column(Numeric, nullable=False)
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        pg_enum(EvidenceType, "evidence_type"), nullable=False
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    finding: Mapped["QAFinding"] = relationship(back_populates="evidence")


class ReviewAction(Base, UUIDPKMixin):
    """Immutable audit log of confirm/reject/correct actions — the human-feedback
    corpus used for future model evaluation/training (Phase 5)."""

    __tablename__ = "review_actions"

    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qa_findings.id"), nullable=False)
    action_type: Mapped[ReviewActionType] = mapped_column(
        pg_enum(ReviewActionType, "review_action_type"), nullable=False
    )
    previous_verdict: Mapped[Verdict | None] = mapped_column(
        pg_enum(Verdict, "verdict"), nullable=True
    )
    new_verdict: Mapped[Verdict | None] = mapped_column(pg_enum(Verdict, "verdict"), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    finding: Mapped["QAFinding"] = relationship(back_populates="review_actions")
