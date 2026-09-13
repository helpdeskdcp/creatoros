"""Auth business logic: registration, login, refresh rotation, logout."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_jwt,
    decode_jwt,
    generate_refresh_token_secret,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.timeutils import ensure_aware
from app.modules.billing.service import ensure_personal_organization
from app.modules.users.models import User, UserRole, UserSession


async def register_user(
    db: AsyncSession, email: str, password: str, full_name: str | None
) -> User:
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise ConflictError("An account with this email already exists")

    user_count = await db.scalar(select(func.count()).select_from(User))
    role = UserRole.OWNER if user_count == 0 else UserRole.VIEWER

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await ensure_personal_organization(db, user.id)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise UnauthorizedError("This account has been deactivated")

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return user


async def issue_tokens(
    db: AsyncSession, user: User, user_agent: str | None, ip_address: str | None
) -> tuple[str, str, int]:
    """Returns (access_token, refresh_token, access_expires_in_seconds)."""
    access_token, access_expires_at = create_jwt(
        subject=str(user.id), token_type="access", extra_claims={"role": user.role.value}
    )

    refresh_secret = generate_refresh_token_secret()
    refresh_token, refresh_expires_at = create_jwt(
        subject=str(user.id),
        token_type="refresh",
        extra_claims={"rtok": refresh_secret},
    )

    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_secret),
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=refresh_expires_at,
    )
    db.add(session)
    await db.commit()

    now = datetime.now(UTC)
    expires_in = int((access_expires_at - now).total_seconds())
    return access_token, refresh_token, expires_in


async def rotate_refresh_token(
    db: AsyncSession, refresh_token: str, user_agent: str | None, ip_address: str | None
) -> tuple[User, str, str, int]:
    try:
        payload = decode_jwt(refresh_token)
    except Exception as exc:  # noqa: BLE001
        raise UnauthorizedError("Invalid or expired refresh token") from exc

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid token type")

    rtok = payload.get("rtok")
    user_id = payload.get("sub")
    if not rtok or not user_id:
        raise UnauthorizedError("Malformed refresh token")

    token_hash = hash_token(rtok)
    session = await db.scalar(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    )
    if not session or session.revoked_at is not None:
        raise UnauthorizedError("Session has been revoked")
    if ensure_aware(session.expires_at) < datetime.now(UTC):
        raise UnauthorizedError("Session has expired")

    user = await db.get(User, uuid.UUID(user_id))
    if not user or not user.is_active:
        raise UnauthorizedError("Account is no longer active")

    # Rotate: revoke the old session, issue a brand new one.
    session.revoked_at = datetime.now(UTC)
    await db.commit()

    new_access, new_refresh, expires_in = await issue_tokens(db, user, user_agent, ip_address)
    return user, new_access, new_refresh, expires_in


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    try:
        payload = decode_jwt(refresh_token)
    except Exception:  # noqa: BLE001
        return
    rtok = payload.get("rtok")
    if not rtok:
        return
    session = await db.scalar(
        select(UserSession).where(UserSession.refresh_token_hash == hash_token(rtok))
    )
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
