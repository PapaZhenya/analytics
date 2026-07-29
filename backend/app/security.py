import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.app.config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


class TokenType(str, Enum):
    access = "access"
    refresh = "refresh"


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": TokenType.access.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID, jti: uuid.UUID | None = None) -> tuple[str, uuid.UUID, datetime]:
    now = datetime.now(timezone.utc)
    jti = jti or uuid.uuid4()
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "type": TokenType.refresh.value,
        "jti": str(jti),
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, expires_at


class TokenPayload:
    def __init__(self, user_id: uuid.UUID, token_type: TokenType, jti: uuid.UUID | None = None):
        self.user_id = user_id
        self.token_type = token_type
        self.jti = jti


def decode_token(token: str, expected_type: TokenType) -> TokenPayload | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None

    if payload.get("type") != expected_type.value:
        return None

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None

    jti = None
    if "jti" in payload:
        try:
            jti = uuid.UUID(payload["jti"])
        except ValueError:
            return None

    return TokenPayload(user_id=user_id, token_type=expected_type, jti=jti)
