"""SQLAlchemy models. Import every module here so Base.metadata / Alembic autogenerate
sees the full schema."""

from backend.app.db.base import Base
from backend.app.models.auth import RefreshToken  # noqa: F401
from backend.app.models.calls import (  # noqa: F401
    AcousticMetrics,
    Call,
    CallFlag,
    CallProcessingStep,
    CallSummary,
    CallTag,
    ProcessingJob,
    Speaker,
    SpeakerRole,
    Utterance,
    UtteranceCorrection,
)
from backend.app.models.collab import Comment, IngestionSource  # noqa: F401
from backend.app.models.org import (  # noqa: F401
    Agent,
    AuditLog,
    Department,
    Organization,
    Permission,
    Project,
    Role,
    RolePermission,
    Team,
    TeamMember,
    User,
)
from backend.app.models.qa import (  # noqa: F401
    QAEvaluation,
    QAFinding,
    QAFindingEvidence,
    ReviewAction,
    Scorecard,
    ScorecardCriterion,
    ScorecardSection,
)

__all__ = ["Base"]
