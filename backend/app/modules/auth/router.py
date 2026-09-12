from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.db.session import get_db
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.modules.users.models import User

router = APIRouter()

REFRESH_COOKIE_NAME = "creatoros_refresh_token"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain if not settings.cookie_domain == "localhost" else None,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path="/",
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await service.register_user(db, payload.email, payload.password, payload.full_name)
    access_token, refresh_token, expires_in = await service.issue_tokens(
        db, user, request.headers.get("user-agent"), request.client.host if request.client else None
    )
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token, expires_in=expires_in, user=UserOut.model_validate(user)
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await service.authenticate_user(db, payload.email, payload.password)
    access_token, refresh_token, expires_in = await service.issue_tokens(
        db, user, request.headers.get("user-agent"), request.client.host if request.client else None
    )
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token, expires_in=expires_in, user=UserOut.model_validate(user)
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise UnauthorizedError("No refresh token present")

    user, access_token, new_refresh_token, expires_in = await service.rotate_refresh_token(
        db, refresh_token, request.headers.get("user-agent"), request.client.host if request.client else None
    )
    _set_refresh_cookie(response, new_refresh_token)
    return TokenResponse(
        access_token=access_token, expires_in=expires_in, user=UserOut.model_validate(user)
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        await service.revoke_refresh_token(db, refresh_token)
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    return None


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)
