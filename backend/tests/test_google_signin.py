"""Google Sign-In: auto-registration for a new Gmail account, straight
login for an existing one, and the CSRF-protected state token -- a
separate, lighter OAuth flow from YouTube channel connection (only
openid/email/profile, works for any Google account regardless of the
YouTube-scope consent screen's verification status)."""
import pytest

from app.core.errors import UnauthorizedError
from app.modules.auth import google_oauth
from app.modules.auth import service as auth_service
from app.modules.users.models import User, UserRole


@pytest.mark.asyncio
async def test_new_google_account_auto_registers_as_owner_when_first_user(db_session):
    user = await auth_service.login_or_register_via_google(
        db_session, "newcreator@gmail.com", "New Creator", email_verified=True,
    )
    assert user.role == UserRole.OWNER
    assert user.email == "newcreator@gmail.com"
    assert user.full_name == "New Creator"


@pytest.mark.asyncio
async def test_second_google_account_is_viewer_not_owner(db_session):
    db_session.add(User(email="existing@example.com", hashed_password="x", role=UserRole.OWNER))
    await db_session.commit()

    user = await auth_service.login_or_register_via_google(
        db_session, "secondcreator@gmail.com", "Second Creator", email_verified=True,
    )
    assert user.role == UserRole.VIEWER


@pytest.mark.asyncio
async def test_existing_email_logs_in_instead_of_duplicating(db_session):
    existing = User(email="already@gmail.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)

    user = await auth_service.login_or_register_via_google(
        db_session, "already@gmail.com", "Whatever Name Google Has", email_verified=True,
    )
    assert user.id == existing.id


@pytest.mark.asyncio
async def test_unverified_google_email_is_rejected(db_session):
    with pytest.raises(UnauthorizedError):
        await auth_service.login_or_register_via_google(
            db_session, "unverified@gmail.com", "Someone", email_verified=False,
        )


@pytest.mark.asyncio
async def test_deactivated_account_cannot_sign_in_via_google(db_session):
    existing = User(email="deactivated@gmail.com", hashed_password="x", role=UserRole.OWNER, is_active=False)
    db_session.add(existing)
    await db_session.commit()

    with pytest.raises(UnauthorizedError):
        await auth_service.login_or_register_via_google(
            db_session, "deactivated@gmail.com", "Someone", email_verified=True,
        )


def test_state_token_round_trips():
    state = google_oauth.build_google_signin_state()
    google_oauth.verify_google_signin_state(state)  # must not raise


def test_state_token_from_a_different_purpose_is_rejected():
    from app.core.security import create_jwt

    wrong_purpose_token, _ = create_jwt(
        subject="x", token_type="access", extra_claims={"purpose": "yt_oauth"}
    )
    with pytest.raises(UnauthorizedError):
        google_oauth.verify_google_signin_state(wrong_purpose_token)


def test_garbage_state_token_is_rejected():
    with pytest.raises(UnauthorizedError):
        google_oauth.verify_google_signin_state("not-a-real-jwt")


@pytest.mark.asyncio
async def test_full_callback_flow_creates_account_and_sets_session(client, monkeypatch):
    state = google_oauth.build_google_signin_state()

    async def _fake_exchange(code: str) -> dict:
        assert code == "mock-google-code"
        return {"email": "browsersignin@gmail.com", "email_verified": True, "name": "Browser Sign In"}

    monkeypatch.setattr(google_oauth, "exchange_code_for_profile", _fake_exchange)

    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock-google-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    assert "access_token=" in resp.headers["location"]
    assert "creatoros_refresh_token" in resp.cookies


@pytest.mark.asyncio
async def test_callback_redirects_with_error_on_google_denial(client):
    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    assert "google_error=access_denied" in resp.headers["location"]


@pytest.mark.asyncio
async def test_callback_redirects_with_error_on_invalid_state(client):
    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "whatever", "state": "garbage"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    assert "google_error=" in resp.headers["location"]
