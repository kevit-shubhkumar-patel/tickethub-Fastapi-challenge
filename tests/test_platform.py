"""Health check, request IDs and the error envelope: things every route depends on."""


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_request_id_is_generated_and_returned(client):
    r = await client.get("/health")
    rid = r.headers["x-request-id"]
    assert len(rid) == 32  # uuid4().hex


async def test_valid_client_request_id_is_echoed(client):
    r = await client.get("/health", headers={"X-Request-ID": "my-trace-123"})
    assert r.headers["x-request-id"] == "my-trace-123"


async def test_unsafe_client_request_id_is_replaced(client):
    r = await client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces"


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/does-not-exist")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert err["request_id"] == r.headers["x-request-id"]


async def test_wrong_method_uses_error_envelope(client):
    r = await client.put("/events")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_validation_error_shape(client):
    r = await client.post("/users", json={"name": "No Email"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["request_id"] == r.headers["x-request-id"]
    assert any("email" in d["loc"] for d in err["details"])