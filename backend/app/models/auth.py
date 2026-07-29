import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, UUIDPKMixin


class RefreshToken(Base, UUIDPKMixin):
    """Server-side record backing refresh-token rotation/revocation.

    Each issued refresh token's jti is stored here. On use, it's checked for
    revocation, then marked revoked and a new row is inserted (rotation) — so a stolen
    refresh token can only be replayed once before rotation invalidates it, and logout
    can revoke it immediately.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    jti: Mapped[uuid.UUID] = mapped_column(unique=True, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
