import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db.session import get_db
from backend.app.dependencies import get_current_user
from backend.app.models.auth import RefreshToken
from backend.app.models.org import AuditLog, Role, User
from backend.app.rate_limit import limiter
from backend.app.schemas.auth import LoginRequest, TokenResponse, UserOut
from backend.app.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)

REFRESH_COOKIE_NAME = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path="/api/v1/auth",
    )


def _user_out(db: Session, user: User) -> UserOut:
    role = db.get(Role, user.role_id)
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role_code=role.code if role else "",
        org_id=user.org_id,
        is_active=user.is_active,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.login_rate_limit)
def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        # Logged (structured, not printed) for brute-force/account-enumeration
        # monitoring — the email is intentionally the only PII in this line, not the
        # attempted password. If the account exists, this is also written to that
        # org's audit_log; a nonexistent email has no org to attach an audit row to,
        # so it's log-only.
        logger.warning(
            "Failed login attempt",
            extra={"attempted_email": body.email, "client_ip": request.client.host if request.client else None},
        )
        if user is not None:
            db.add(
                AuditLog(
                    id=uuid.uuid4(),
                    org_id=user.org_id,
                    user_id=user.id,
                    action="login_failed",
                    entity_type="user",
                    entity_id=user.id,
                    audit_metadata={},
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        # Same error for "no such user" and "wrong password" — do not leak which one.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    access_token = create_access_token(user.id)
    refresh_token, jti, expires_at = create_refresh_token(user.id)

    db.add(
        RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            jti=jti,
            issued_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
    )
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            org_id=user.org_id,
            user_id=user.id,
            action="login",
            entity_type="user",
            entity_id=user.id,
            audit_metadata={},
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")

    payload = decode_token(token, expected_type=TokenType.refresh)
    if payload is None or payload.jti is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    record = db.execute(
        select(RefreshToken).where(RefreshToken.jti == payload.jti)
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at.replace(tzinfo=timezone.utc) < now
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired or revoked")

    user = db.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    # Rotate: revoke the used token, issue a new one. A replayed (stolen) refresh token
    # can only be used once before rotation invalidates it.
    record.revoked_at = now
    new_refresh_token, new_jti, new_expires_at = create_refresh_token(user.id)
    db.add(
        RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            jti=new_jti,
            issued_at=now,
            expires_at=new_expires_at,
        )
    )
    db.commit()

    _set_refresh_cookie(response, new_refresh_token)
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    return _user_out(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if token is not None:
        payload = decode_token(token, expected_type=TokenType.refresh)
        if payload is not None and payload.jti is not None:
            record = db.execute(
                select(RefreshToken).where(RefreshToken.jti == payload.jti)
            ).scalar_one_or_none()
            if record is not None and record.revoked_at is None:
                record.revoked_at = datetime.now(timezone.utc)
                db.commit()

    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")
