"""Google Sign-In for CreatorOS's own login/registration -- a separate,
lighter OAuth flow from the YouTube channel-connection flow in
app.modules.channels.service. Requests only openid/email/profile (never
a "sensitive" scope), so it works for any Gmail user regardless of
whether the app's YouTube-scope OAuth consent screen has completed
Google's extended verification.

Reuses the same Google Cloud OAuth client (YOUTUBE_CLIENT_ID/SECRET) --
one OAuth app can request different scopes for different flows; this is
not the same grant as the YouTube channel connection.
"""
import uuid

import httpx
import jwt

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.security import create_jwt, decode_jwt

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_SCOPES = "openid email profile"


class GoogleOAuthError(Exception):
    pass


def build_google_signin_state() -> str:
    """A pure CSRF nonce (no user id -- there is no logged-in CreatorOS
    user yet at this point in the flow) signed the same way as every
    other state token in this codebase."""
    token, _ = create_jwt(
        subject=str(uuid.uuid4()), token_type="access", extra_claims={"purpose": "google_signin"}
    )
    return token


def verify_google_signin_state(state: str) -> None:
    try:
        payload = decode_jwt(state)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Google sign-in state is invalid or has expired") from exc
    if payload.get("purpose") != "google_signin":
        raise UnauthorizedError("State was not issued for Google sign-in")


def get_google_authorize_url(state: str) -> str:
    settings = get_settings()
    params = (
        f"client_id={settings.youtube_client_id}"
        f"&redirect_uri={settings.google_signin_redirect_uri}"
        f"&response_type=code"
        f"&scope={GOOGLE_SCOPES.replace(' ', '+')}"
        f"&state={state}"
        f"&access_type=online"
        f"&prompt=select_account"
    )
    return f"{GOOGLE_AUTH_BASE}?{params}"


async def exchange_code_for_profile(code: str) -> dict:
    """Returns {"email": str, "email_verified": bool, "name": str | None}."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "redirect_uri": settings.google_signin_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise GoogleOAuthError(f"Failed to exchange Google auth code: {token_resp.text}")
        access_token = token_resp.json()["access_token"]

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_resp.status_code != 200:
            raise GoogleOAuthError(f"Failed to fetch Google profile: {userinfo_resp.text}")

    profile = userinfo_resp.json()
    email = profile.get("email")
    if not email:
        raise GoogleOAuthError("Google did not return an email address for this account")
    return {
        "email": email,
        "email_verified": bool(profile.get("verified_email", False)),
        "name": profile.get("name"),
    }
