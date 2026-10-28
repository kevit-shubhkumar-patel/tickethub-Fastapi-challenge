import pytest

from tests.helpers import create_user

MISSING_ID = "000000000000000000000000"


# ---------- POST /users ----------

async def test_create_user_defaults(client):
    r = await client.post("/users", json={"email": "Asha@Test.com", "name": "Asha"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "asha@test.com"  # lowercased
    assert body["role"] == "attendee"  # default role
    assert body["is_active"] is True
    assert {"id", "created_at", "updated_at"} <= body.keys()


async def test_duplicate_email_is_409_case_insensitive(client):
    assert (await client.post("/users", json={"email": "a@x.com", "name": "A"})).status_code == 201
    r = await client.post("/users", json={"email": "A@X.com", "name": "B"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize("body", [
    {"email": "a@x.com", "name": "A", "age": 20},           # unknown field
    {"email": "not-an-email", "name": "A"},                 # bad email
    {"email": "a@x.com", "name": "A", "role": "superuser"},  # bad role
    {"email": "a@x.com", "name": ""},                       # empty name
    {"name": "A"},                                          # missing email
])
async def test_create_user_invalid_body_is_422(client, body):
    r = await client.post("/users", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------- GET /users/{id} ----------

async def test_get_user(client):
    user = await create_user(client)
    r = await client.get(f"/users/{user['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == user["id"]


async def test_get_user_malformed_id_is_422(client):
    assert (await client.get("/users/abc")).status_code == 422


async def test_get_user_missing_is_404(client):
    r = await client.get(f"/users/{MISSING_ID}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


# ---------- GET /users (pagination) ----------

async def test_list_users_pagination_returns_each_once(client):
    for _ in range(25):
        await create_user(client)

    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 10, **({"cursor": cursor} if cursor else {})}
        body = (await client.get("/users", params=params)).json()
        seen += [u["id"] for u in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 25
    assert len(set(seen)) == 25  # no duplicates


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"cursor": "abc"}])
async def test_list_users_bad_params_are_422(client, params):
    assert (await client.get("/users", params=params)).status_code == 422


# ---------- PATCH /users/{id} ----------

async def test_patch_user_name(client):
    user = await create_user(client)
    r = await client.patch(f"/users/{user['id']}", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    assert r.json()["email"] == user["email"]  # untouched


@pytest.mark.parametrize("body", [
    {},                        # empty body
    {"name": None},            # explicit null
    {"email": "new@x.com"},    # email isn't editable
    {"role": "superuser"},     # bad enum
])
async def test_patch_user_invalid_is_422(client, body):
    user = await create_user(client)
    assert (await client.patch(f"/users/{user['id']}", json=body)).status_code == 422


async def test_patch_missing_user_is_404(client):
    assert (await client.patch(f"/users/{MISSING_ID}", json={"name": "X"})).status_code == 404


# ---------- DELETE /users/{id} ----------

async def test_delete_user_is_soft(client):
    user = await create_user(client)
    assert (await client.delete(f"/users/{user['id']}")).status_code == 204
    r = await client.get(f"/users/{user['id']}")
    assert r.status_code == 200
    assert r.json()["is_active"] is False


async def test_delete_missing_user_is_404(client):
    assert (await client.delete(f"/users/{MISSING_ID}")).status_code == 404