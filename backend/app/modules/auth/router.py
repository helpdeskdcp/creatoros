from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.db.session import get_db
from app.modules.auth import google_oauth, service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import GoogleAuthorizeResponse, LoginRequest, RegisterRequest, TokenResponse, UserOut
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


@router.get("/google/authorize", response_model=GoogleAuthorizeResponse)
async def google_authorize():
    """Google Sign-In (login/registration) -- distinct from the YouTube
    channel-connection OAuth flow. Requires no logged-in user: this IS
    how a new creator gets an account."""
    state = google_oauth.build_google_signin_state()
    return GoogleAuthorizeResponse(authorize_url=google_oauth.get_google_authorize_url(state))


@router.get("/google/callback")
async def google_callback(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    settings = get_settings()
    frontend_origin = settings.cors_origin_list[0] if settings.cors_origin_list else ""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return RedirectResponse(f"{frontend_origin}/login?google_error={error}")
    if not code or not state:
        return RedirectResponse(f"{frontend_origin}/login?google_error=missing_code_or_state")

    try:
        google_oauth.verify_google_signin_state(state)
        profile = await google_oauth.exchange_code_for_profile(code)
        user = await service.login_or_register_via_google(
            db, profile["email"], profile["name"], profile["email_verified"],
        )
    except (UnauthorizedError, google_oauth.GoogleOAuthError) as exc:
        return RedirectResponse(f"{frontend_origin}/login?google_error={exc}")

    access_token, refresh_token, expires_in = await service.issue_tokens(
        db, user, request.headers.get("user-agent"), request.client.host if request.client else None
    )
    redirect = RedirectResponse(f"{frontend_origin}/auth/google/complete?access_token={access_token}&expires_in={expires_in}")
    _set_refresh_cookie(redirect, refresh_token)
    return redirect
