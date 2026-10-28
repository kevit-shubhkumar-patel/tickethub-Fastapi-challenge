"""Shared helpers for building test data. Every helper goes through the API except the
`db_*` ones, which reach into Mongo to simulate things the API can't do yet (payment
confirmation, time passing)."""
import uuid
from datetime import UTC, datetime, timedelta

from bson import ObjectId

from app.db import client as db


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.com"


async def create_user(client, *, role: str = "attendee", name: str = "Test User") -> dict:
    r = await client.post("/users", json={"email": unique_email(role), "name": name, "role": role})
    assert r.status_code == 201, r.text
    return r.json()


def future(days: int = 7, hours: int = 0) -> datetime:
    return (datetime.now(UTC) + timedelta(days=days, hours=hours)).replace(microsecond=0)


def event_body(organizer_id: str, **overrides) -> dict:
    """A valid EventCreate body: VIP (quota 10, ₹2000) + General (quota 80, ₹800), capacity 100."""
    # start = overrides.pop("starts_at", future())
    # end = overrides.pop("ends_at", start + timedelta(hours=4))
    start = overrides.pop("starts_at", None) or future()
    end = overrides.pop("ends_at", None)
    if end is None:
        end = start + timedelta(hours=4)  # only computed when the test didn't supply one
    body = {
        "title": "Rock Night",
        "venue": {"name": "Arena", "city": "Pune"},
        "starts_at": start.isoformat() if isinstance(start, datetime) else start,
        "ends_at": end.isoformat() if isinstance(end, datetime) else end,
        "capacity": 100,
        "ticket_tiers": [
            {"name": "VIP", "price_inr": 2000, "quota": 10},
            {"name": "General", "price_inr": 800, "quota": 80},
        ],
        "organizer_id": organizer_id,
    }
    body.update(overrides)
    return body


async def create_event(client, organizer_id: str | None = None, *, publish: bool = False, **overrides) -> dict:
    if organizer_id is None:
        organizer_id = (await create_user(client, role="organizer"))["id"]
    r = await client.post("/events", json=event_body(organizer_id, **overrides))
    assert r.status_code == 201, r.text
    event = r.json()
    if publish:
        r = await client.post(f"/events/{event['id']}/publish")
        assert r.status_code == 200, r.text
        event = r.json()
    return event


async def create_booking(client, event_id: str, user_id: str, *, tier: str = "VIP", quantity: int = 1) -> dict:
    r = await client.post("/bookings", json={
        "event_id": event_id, "tier": tier, "quantity": quantity, "user_id": user_id,
    })
    assert r.status_code == 201, r.text
    return r.json()


def tier_remaining(event: dict, tier: str) -> int:
    return next(t["remaining"] for t in event["ticket_tiers"] if t["name"] == tier)


async def get_remaining(client, event_id: str, tier: str = "VIP") -> int:
    return tier_remaining((await client.get(f"/events/{event_id}")).json(), tier)


# ---- direct DB helpers: simulate what later phases will do ----

async def db_confirm_booking(booking_id: str) -> None:
    """Stand-in for the Phase 6 payment webhook."""
    await db.get_db()["bookings"].update_one(
        {"_id": ObjectId(booking_id)}, {"$set": {"status": "confirmed", "hold_expires_at": None}}
    )


async def db_set_event_times(event_id: str, starts_at: datetime, ends_at: datetime) -> None:
    """Simulate time passing, since the API won't let you move a published event into the past."""
    await db.get_db()["events"].update_one(
        {"_id": ObjectId(event_id)}, {"$set": {"starts_at": starts_at, "ends_at": ends_at}}
    )