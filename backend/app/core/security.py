"""Password hashing and JWT helpers used by the auth module."""
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_jwt(
    subject: str, token_type: TokenType, extra_claims: dict[str, Any] | None = None
) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    if token_type == "access":
        expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expires_at = now + timedelta(days=settings.refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_jwt(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_refresh_token_secret() -> str:
    """A high-entropy opaque string embedded as the refresh JWT's identifying claim."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """One-way hash used to store refresh tokens so a DB leak doesn't leak usable tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
