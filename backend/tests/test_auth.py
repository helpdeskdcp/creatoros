import pytest


@pytest.mark.asyncio
async def test_register_first_user_becomes_owner(client, unique_email):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "supersecurepassword1", "full_name": "Test Owner"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["role"] == "OWNER"
    assert body["user"]["email"] == unique_email
    assert "access_token" in body
    assert "creatoros_refresh_token" in resp.cookies


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(client, unique_email):
    payload = {"email": unique_email, "password": "supersecurepassword1"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client, unique_email):
    await client.post(
        "/api/v1/auth/register", json={"email": unique_email, "password": "supersecurepassword1"}
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "wrong-password"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_login_success_and_me_endpoint(client, unique_email):
    await client.post(
        "/api/v1/auth/register", json={"email": unique_email, "password": "supersecurepassword1"}
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "supersecurepassword1"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == unique_email


@pytest.mark.asyncio
async def test_protected_route_without_token_is_401(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_old_refresh_fails(client, unique_email):
    await client.post(
        "/api/v1/auth/register", json={"email": unique_email, "password": "supersecurepassword1"}
    )
    old_refresh_cookie = client.cookies.get("creatoros_refresh_token")

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200

    client.cookies.set("creatoros_refresh_token", old_refresh_cookie)
    reused = await client.post("/api/v1/auth/refresh")
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_session(client, unique_email):
    await client.post(
        "/api/v1/auth/register", json={"email": unique_email, "password": "supersecurepassword1"}
    )
    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 401


@pytest.mark.asyncio
async def test_second_user_is_not_owner_and_cannot_list_users(client, unique_email):
    await client.post(
        "/api/v1/auth/register", json={"email": unique_email, "password": "supersecurepassword1"}
    )
    other_email = f"second-{unique_email}"
    second = await client.post(
        "/api/v1/auth/register", json={"email": other_email, "password": "supersecurepassword1"}
    )
    assert second.json()["user"]["role"] == "VIEWER"
    token = second.json()["access_token"]

    resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
