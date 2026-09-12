"""FastAPI dependencies for authentication and role-based access control."""
import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_jwt
from app.db.session import get_db
from app.modules.users.models import User, UserRole

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Missing bearer token")

    try:
        payload = decode_jwt(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid access token") from exc

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Malformed access token")

    user = await db.get(User, uuid.UUID(user_id))
    if not user or not user.is_active:
        raise UnauthorizedError("Account is no longer active")

    return user


def require_roles(*allowed_roles: UserRole) -> Callable:
    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise ForbiddenError(
                f"This action requires one of the following roles: "
                f"{', '.join(r.value for r in allowed_roles)}"
            )
        return user

    return _dependency


# Convenience shorthands for the most common role gates.
require_owner = require_roles(UserRole.OWNER)
require_admin = require_roles(UserRole.OWNER, UserRole.ADMIN)
require_editor = require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.EDITOR)
require_analyst = require_roles(
    UserRole.OWNER, UserRole.ADMIN, UserRole.EDITOR, UserRole.ANALYST
)
