import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, TimestampMixin, UUIDPKMixin, pg_enum


class Comment(Base, UUIDPKMixin):
    __tablename__ = "comments"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    utterance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("utterances.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parent_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IngestionSourceType(str, enum.Enum):
    voiso = "voiso"
    asterisk = "asterisk"
    sftp = "sftp"
    object_storage = "object_storage"
    rest_api = "rest_api"
    webhook = "webhook"
    csv_import = "csv_import"


class IngestionSource(Base, UUIDPKMixin, TimestampMixin):
    """Forward-compatible placeholder backing the Phase 3 telephony connector interface
    (backend/pipeline/ingestion/base.py::IngestionConnector). Unused by Phase 1 code paths.
    """

    __tablename__ = "ingestion_sources"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    type: Mapped[IngestionSourceType] = mapped_column(
        pg_enum(IngestionSourceType, "ingestion_source_type"), nullable=False
    )
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
