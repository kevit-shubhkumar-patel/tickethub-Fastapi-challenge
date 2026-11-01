from datetime import timedelta

import jwt

from app.core.config import settings
from app.core.security import create_access_token
from app.db import client as db

PASSWORD = "correct-horse-battery"


# ---------- helpers ----------

async def register_and_login(client, email: str = "a@test.com") -> tuple[dict, str]:
    """Register an attendee, log in, and return (user, access_token)."""
    r = await client.post("/auth/register", json={"email": email, "name": "A", "password": PASSWORD})
    assert r.status_code == 201, r.text
    user = r.json()

    r = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return user, r.json()["access_token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------- POST /auth/register ----------

async def test_register_creates_attendee(client):
    r = await client.post("/auth/register", json={
        "email": "New@Test.com", "name": "New", "password": PASSWORD,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "attendee"
    assert body["email"] == "new@test.com"
    assert "password" not in body and "password_hash" not in body


async def test_password_is_stored_hashed(client):
    await client.post("/auth/register", json={
        "email": "a@test.com", "name": "A", "password": PASSWORD,
    })
    doc = await db.get_db()["users"].find_one({"email": "a@test.com"})
    assert doc["password_hash"].startswith("$argon2")
    assert PASSWORD not in doc["password_hash"]


async def test_register_rejects_role(client):
    r = await client.post("/auth/register", json={
        "email": "a@test.com", "name": "A", "password": PASSWORD, "role": "admin",
    })
    assert r.status_code == 422


async def test_register_short_password(client):
    r = await client.post("/auth/register", json={"email": "a@test.com", "name": "A", "password": "short"})
    assert r.status_code == 422


async def test_register_duplicate_email(client):
    body = {"email": "a@test.com", "name": "A", "password": PASSWORD}
    assert (await client.post("/auth/register", json=body)).status_code == 201
    body["email"] = "A@TEST.com"
    r = await client.post("/auth/register", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


# ---------- POST /auth/login ----------

async def test_login_returns_token_with_required_claims(client):
    _, token = await register_and_login(client)
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    assert {"sub", "role", "jti", "exp"} <= claims.keys()
    assert claims["role"] == "attendee"


async def test_login_response_shape(client):
    await client.post("/auth/register", json={"email": "a@test.com", "name": "A", "password": PASSWORD})
    r = await client.post("/auth/login", data={"username": "a@test.com", "password": PASSWORD})
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_minutes * 60


async def test_login_email_is_case_insensitive(client):
    await register_and_login(client)
    r = await client.post("/auth/login", data={"username": "A@TEST.com", "password": PASSWORD})
    assert r.status_code == 200


async def test_wrong_password_and_unknown_email_look_identical(client):
    await register_and_login(client)
    wrong_pw = await client.post("/auth/login", data={"username": "a@test.com", "password": "wrong-password-123"})
    no_user = await client.post("/auth/login", data={"username": "nobody@test.com", "password": PASSWORD})

    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["code"] == no_user.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"]


async def test_user_without_password_cannot_login(client):
    await client.post("/users", json={"email": "nopw@test.com", "name": "No PW"})
    r = await client.post("/auth/login", data={"username": "nopw@test.com", "password": PASSWORD})
    assert r.status_code == 401


async def test_deactivated_user_cannot_login(client):
    user, _ = await register_and_login(client)
    await client.delete(f"/users/{user['id']}")
    r = await client.post("/auth/login", data={"username": "a@test.com", "password": PASSWORD})
    assert r.status_code == 401


# ---------- GET /auth/me ----------

async def test_me_with_token(client):
    user, token = await register_and_login(client)
    r = await client.get("/auth/me", headers=bearer(token))
    assert r.status_code == 200
    assert r.json()["id"] == user["id"]
    assert "password_hash" not in r.json()


async def test_me_without_token(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert r.headers["www-authenticate"] == "Bearer"


async def test_me_with_garbage_token(client):
    r = await client.get("/auth/me", headers=bearer("not-a-jwt"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_expired_token(client):
    user, _ = await register_and_login(client)
    expired = create_access_token(user["id"], "attendee", expires_delta=timedelta(seconds=-1))
    r = await client.get("/auth/me", headers=bearer(expired))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_token_signed_with_wrong_secret(client):
    """A forged token claiming to be admin, signed with the wrong key, is rejected."""
    _, token = await register_and_login(client)
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    forged = jwt.encode(claims | {"role": "admin"}, "attacker-secret", algorithm="HS256")
    r = await client.get("/auth/me", headers=bearer(forged))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_deactivated_user_token_stops_working(client):
    user, token = await register_and_login(client)
    await client.delete(f"/users/{user['id']}")
    r = await client.get("/auth/me", headers=bearer(token))
    assert r.status_code == 401