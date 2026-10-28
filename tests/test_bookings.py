import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import (
    create_booking, create_event, create_user, db_confirm_booking, db_set_event_times, get_remaining,
)

MISSING_ID = "000000000000000000000000"


@pytest.fixture
async def setup(client):
    """A published event (VIP quota 10 @ ₹2000, General quota 80 @ ₹800) and one attendee."""
    event = await create_event(client, publish=True)
    user = await create_user(client)
    return {"event": event, "user": user}


def booking_body(setup, **overrides) -> dict:
    body = {"event_id": setup["event"]["id"], "tier": "VIP", "quantity": 2, "user_id": setup["user"]["id"]}
    body.update(overrides)
    return body


# ---------- POST /bookings ----------

async def test_create_booking(client, setup):
    r = await client.post("/bookings", json=booking_body(setup))
    assert r.status_code == 201
    b = r.json()
    assert b["amount_inr"] == 4000  # 2 × 2000, computed by the server
    assert b["status"] == "pending_payment"
    hold = datetime.fromisoformat(b["hold_expires_at"])
    assert timedelta(minutes=14) < hold - datetime.now(UTC) <= timedelta(minutes=15)


async def test_create_booking_reserves_seats(client, setup):
    await client.post("/bookings", json=booking_body(setup, quantity=3))
    assert await get_remaining(client, setup["event"]["id"], "VIP") == 7
    assert await get_remaining(client, setup["event"]["id"], "General") == 80  # other tier untouched


@pytest.mark.parametrize("overrides", [
    {"quantity": 0},
    {"quantity": 7},
    {"amount_inr": 1},          # clients can't set the price
    {"status": "confirmed"},    # clients can't set the status
    {"event_id": "abc"},
    {"tier": ""},
])
async def test_create_booking_invalid_body_is_422(client, setup, overrides):
    r = await client.post("/bookings", json=booking_body(setup, **overrides))
    assert r.status_code == 422


@pytest.mark.parametrize("tier", ["Gold", "vip"])  # unknown, and wrong case
async def test_create_booking_unknown_tier(client, setup, tier):
    r = await client.post("/bookings", json=booking_body(setup, tier=tier))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_TIER"


async def test_create_booking_missing_event_is_404(client, setup):
    assert (await client.post("/bookings", json=booking_body(setup, event_id=MISSING_ID))).status_code == 404


async def test_create_booking_missing_user_is_404(client, setup):
    assert (await client.post("/bookings", json=booking_body(setup, user_id=MISSING_ID))).status_code == 404


async def test_create_booking_inactive_user_is_404(client, setup):
    await client.delete(f"/users/{setup['user']['id']}")
    assert (await client.post("/bookings", json=booking_body(setup))).status_code == 404


async def test_cannot_book_draft_event(client, setup):
    draft = await create_event(client)
    r = await client.post("/bookings", json=booking_body(setup, event_id=draft["id"]))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EVENT_NOT_BOOKABLE"


async def test_cannot_book_cancelled_event(client, setup):
    await client.post(f"/events/{setup['event']['id']}/cancel")
    r = await client.post("/bookings", json=booking_body(setup))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EVENT_NOT_BOOKABLE"


async def test_cannot_book_started_event(client, setup):
    now = datetime.now(UTC)
    await db_set_event_times(setup["event"]["id"], now - timedelta(hours=1), now + timedelta(hours=2))
    assert (await client.post("/bookings", json=booking_body(setup))).status_code == 409


async def test_sold_out(client, setup):
    assert (await client.post("/bookings", json=booking_body(setup, quantity=6))).status_code == 201
    r = await client.post("/bookings", json=booking_body(setup, quantity=6))  # only 4 left
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SOLD_OUT"
    assert await get_remaining(client, setup["event"]["id"]) == 4  # failed booking took nothing


async def test_no_overselling_under_concurrency(client, setup):  # R1.2
    event_id = setup["event"]["id"]
    user_ids = [(await create_user(client))["id"] for _ in range(50)]

    results = await asyncio.gather(*[
        client.post("/bookings", json={"event_id": event_id, "tier": "VIP", "quantity": 1, "user_id": uid})
        for uid in user_ids
    ])

    codes = [r.status_code for r in results]
    assert codes.count(201) == 10
    assert codes.count(409) == 40
    assert all(r.json()["error"]["code"] == "SOLD_OUT" for r in results if r.status_code == 409)
    assert await get_remaining(client, event_id) == 0


# ---------- GET /bookings/{id} ----------

async def test_get_booking(client, setup):
    b = await create_booking(client, setup["event"]["id"], setup["user"]["id"])
    r = await client.get(f"/bookings/{b['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == b["id"]


async def test_get_booking_malformed_id_is_422(client):
    assert (await client.get("/bookings/abc")).status_code == 422


async def test_get_booking_missing_is_404(client):
    assert (await client.get(f"/bookings/{MISSING_ID}")).status_code == 404


# ---------- GET /bookings ----------

async def test_list_bookings_filters(client, setup):
    event_id, asha = setup["event"]["id"], setup["user"]["id"]
    ravi = (await create_user(client))["id"]
    b1 = await create_booking(client, event_id, asha, tier="General")
    await create_booking(client, event_id, asha, tier="General")
    await create_booking(client, event_id, ravi, tier="General")
    await client.delete(f"/bookings/{b1['id']}")

    by_user = (await client.get("/bookings", params={"user_id": asha})).json()["items"]
    assert len(by_user) == 2

    by_event = (await client.get("/bookings", params={"event_id": event_id})).json()["items"]
    assert len(by_event) == 3

    cancelled = (await client.get("/bookings", params={"status": "cancelled"})).json()["items"]
    assert [b["id"] for b in cancelled] == [b1["id"]]

    combined = (await client.get("/bookings", params={"user_id": asha, "status": "pending_payment"})).json()
    assert len(combined["items"]) == 1


async def test_list_bookings_pagination(client, setup):
    for _ in range(5):
        await create_booking(client, setup["event"]["id"], setup["user"]["id"], tier="General")

    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (await client.get("/bookings", params=params)).json()
        seen += [b["id"] for b in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5
    assert len(set(seen)) == 5


@pytest.mark.parametrize("params", [{"status": "paid"}, {"cursor": "abc"}, {"event_id": "abc"}, {"limit": 101}])
async def test_list_bookings_bad_params_are_422(client, params):
    assert (await client.get("/bookings", params=params)).status_code == 422


# ---------- PATCH /bookings/{id} (R1.6) ----------

@pytest.mark.parametrize("target", ["confirmed", "checked_in", "expired", "refunded", "pending_payment"])
async def test_user_cannot_make_illegal_transitions(client, setup, target):
    b = await create_booking(client, setup["event"]["id"], setup["user"]["id"])
    r = await client.patch(f"/bookings/{b['id']}", json={"status": target})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ILLEGAL_TRANSITION"


@pytest.mark.parametrize("body", [{}, {"status": "done"}, {"status": "cancelled", "quantity": 3}])
async def test_patch_booking_invalid_body_is_422(client, setup, body):
    b = await create_booking(client, setup["event"]["id"], setup["user"]["id"])
    assert (await client.patch(f"/bookings/{b['id']}", json=body)).status_code == 422


async def test_patch_cancel_releases_seats_and_clears_hold(client, setup):
    event_id = setup["event"]["id"]
    b = await create_booking(client, event_id, setup["user"]["id"], quantity=3)
    assert await get_remaining(client, event_id) == 7

    r = await client.patch(f"/bookings/{b['id']}", json={"status": "cancelled"})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert r.json()["hold_expires_at"] is None
    assert await get_remaining(client, event_id) == 10

    again = await client.patch(f"/bookings/{b['id']}", json={"status": "cancelled"})
    assert again.status_code == 409
    assert await get_remaining(client, event_id) == 10  # not released twice


async def test_patch_missing_booking_is_404(client):
    assert (await client.patch(f"/bookings/{MISSING_ID}", json={"status": "cancelled"})).status_code == 404


# ---------- DELETE /bookings/{id} ----------

async def test_delete_cancels_and_keeps_record(client, setup):
    event_id = setup["event"]["id"]
    b = await create_booking(client, event_id, setup["user"]["id"], quantity=2)

    assert (await client.delete(f"/bookings/{b['id']}")).status_code == 204
    r = await client.get(f"/bookings/{b['id']}")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert await get_remaining(client, event_id) == 10

    assert (await client.delete(f"/bookings/{b['id']}")).status_code == 409


async def test_concurrent_cancels_release_seats_once(client, setup):
    event_id = setup["event"]["id"]
    b = await create_booking(client, event_id, setup["user"]["id"], quantity=3)

    results = await asyncio.gather(*[client.delete(f"/bookings/{b['id']}") for _ in range(5)])
    codes = [r.status_code for r in results]
    assert codes.count(204) == 1
    assert codes.count(409) == 4
    assert await get_remaining(client, event_id) == 10  # not 10 + 3×N


async def test_delete_missing_booking_is_404(client):
    assert (await client.delete(f"/bookings/{MISSING_ID}")).status_code == 404


# ---------- POST /bookings/{id}/check-in ----------

async def test_cannot_check_in_unpaid_booking(client, setup):
    b = await create_booking(client, setup["event"]["id"], setup["user"]["id"])
    r = await client.post(f"/bookings/{b['id']}/check-in")
    assert r.status_code == 409


async def test_check_in_confirmed_booking(client, setup):
    b = await create_booking(client, setup["event"]["id"], setup["user"]["id"])
    await db_confirm_booking(b["id"])  # stand-in for the payment webhook

    r = await client.post(f"/bookings/{b['id']}/check-in")
    assert r.status_code == 200
    assert r.json()["status"] == "checked_in"

    assert (await client.post(f"/bookings/{b['id']}/check-in")).status_code == 409  # twice
    assert (await client.delete(f"/bookings/{b['id']}")).status_code == 409         # can't cancel after entry


async def test_cancel_confirmed_booking_releases_seats(client, setup):
    event_id = setup["event"]["id"]
    b = await create_booking(client, event_id, setup["user"]["id"], quantity=4)
    await db_confirm_booking(b["id"])

    assert (await client.delete(f"/bookings/{b['id']}")).status_code == 204
    assert await get_remaining(client, event_id) == 10


async def test_check_in_missing_booking_is_404(client):
    assert (await client.post(f"/bookings/{MISSING_ID}/check-in")).status_code == 404