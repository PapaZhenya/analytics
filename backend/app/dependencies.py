import uuid
from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.calls import Call
from backend.app.models.org import Permission, RolePermission, User
from backend.app.security import TokenType, decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    payload = decode_token(credentials.credentials, expected_type=TokenType.access)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    return user


def _user_has_permission(db: Session, user: User, permission_code: str) -> bool:
    stmt = (
        select(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == user.role_id, Permission.code == permission_code)
    )
    return db.execute(stmt).first() is not None


def require_permission(permission_code: str):
    """FastAPI dependency factory enforcing RBAC server-side.

    Every router endpoint that touches call/finding/comment/scorecard data must depend on
    this — the frontend's ProtectedRoute/hidden buttons are UX only and enforce nothing.
    """

    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not _user_has_permission(db, user, permission_code):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Missing required permission: {permission_code}",
            )
        return user

    return dependency


def get_call_or_404(db: Session, call_id: uuid.UUID, org_id: uuid.UUID) -> Call:
    """Shared across routers/{calls,audio,transcripts}.py — previously duplicated
    ad hoc in calls.py; centralized here instead of copy-pasted per file.

    Requires `org_id` and enforces it: a call belonging to a different organization
    404s exactly like a nonexistent one (never 403) — a 403 would confirm the call ID
    exists in someone else's org, which is itself information disclosure across a
    tenant boundary. This is real defense-in-depth even in the current single-org
    deployment (every Call row already carries org_id) — schema and enforcement are
    ready together for whenever multi-tenancy is actually turned on, rather than the
    schema alone being ready and the enforcement being added later under pressure.
    """
    call = db.get(Call, call_id)
    if call is None or call.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")
    return call


__all__ = ["get_db", "get_current_user", "require_permission", "get_call_or_404"]
