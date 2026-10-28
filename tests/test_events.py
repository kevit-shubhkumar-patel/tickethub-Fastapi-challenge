from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import (
    create_event, create_user, db_set_event_times, event_body, future, tier_remaining,
)

MISSING_ID = "000000000000000000000000"


# ---------- POST /events ----------

async def test_create_event(client):
    org = await create_user(client, role="organizer")
    r = await client.post("/events", json=event_body(org["id"]))
    assert r.status_code == 201
    ev = r.json()
    assert ev["status"] == "draft"
    assert ev["version"] == 1
    assert ev["organizer_id"] == org["id"]
    assert tier_remaining(ev, "VIP") == 10  # remaining starts at quota
    assert tier_remaining(ev, "General") == 80


@pytest.mark.parametrize("field", [
    "title", "venue", "starts_at", "ends_at", "capacity", "ticket_tiers", "organizer_id",
])
async def test_create_event_missing_required_field_is_422(client, field):
    body = event_body(MISSING_ID)
    del body[field]
    assert (await client.post("/events", json=body)).status_code == 422


@pytest.mark.parametrize("overrides", [
    {"starts_at": "2026-12-10T19:00:00", "ends_at": "2026-12-10T23:00:00"},  # no timezone
    {"title": "Show"},                                                      # title < 5 chars
    {"capacity": 0},
    {"capacity": 50_001},
    {"ticket_tiers": []},                                                   # no tiers
    {"status": "published"},                                                # server-controlled
    {"venue": {"name": "Arena"}},                                           # venue missing city
    {"ticket_tiers": [{"name": "VIP", "price_inr": 2000, "quota": 150}]},   # quota > capacity
    {"ticket_tiers": [                                                      # duplicate names
        {"name": "VIP", "price_inr": 2000, "quota": 10},
        {"name": "vip", "price_inr": 1000, "quota": 10},
    ]},
    {"ticket_tiers": [{"name": "VIP", "price_inr": -1, "quota": 10}]},      # negative price
])
async def test_create_event_invalid_is_422(client, overrides):
    org = await create_user(client, role="organizer")
    assert (await client.post("/events", json=event_body(org["id"], **overrides))).status_code == 422


async def test_create_event_end_before_start_is_422(client):
    org = await create_user(client, role="organizer")
    start = future()
    body = event_body(org["id"], starts_at=start, ends_at=start - timedelta(hours=1))
    assert (await client.post("/events", json=body)).status_code == 422


# ---------- GET /events/{id} ----------

async def test_get_event_sets_etag(client):
    ev = await create_event(client)
    r = await client.get(f"/events/{ev['id']}")
    assert r.status_code == 200
    assert r.headers["etag"] == '"1"'


async def test_get_event_malformed_id_is_422(client):
    assert (await client.get("/events/abc")).status_code == 422


async def test_get_event_missing_is_404(client):
    assert (await client.get(f"/events/{MISSING_ID}")).status_code == 404


# ---------- PATCH /events/{id}: optimistic locking (R1.5) ----------

async def test_optimistic_locking(client):
    ev = await create_event(client)
    url = f"/events/{ev['id']}"

    r = await client.patch(url, json={"title": "New title"})
    assert r.status_code == 428
    assert r.json()["error"]["code"] == "PRECONDITION_REQUIRED"

    assert (await client.patch(url, json={"title": "New title"}, headers={"If-Match": "abc"})).status_code == 422

    ok = await client.patch(url, json={"title": "New title"}, headers={"If-Match": "1"})
    assert ok.status_code == 200
    assert ok.json()["version"] == 2

    stale = await client.patch(url, json={"title": "Other title"}, headers={"If-Match": "1"})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


async def test_if_match_accepts_quoted_etag(client):
    ev = await create_event(client)
    r = await client.patch(f"/events/{ev['id']}", json={"title": "Quoted works"}, headers={"If-Match": '"1"'})
    assert r.status_code == 200


async def test_patch_missing_event_is_404(client):
    r = await client.patch(f"/events/{MISSING_ID}", json={"title": "Nobody"}, headers={"If-Match": "1"})
    assert r.status_code == 404


# ---------- PATCH /events/{id}: what can change ----------

async def test_patch_only_title_keeps_other_fields(client):
    ev = await create_event(client)
    r = await client.patch(f"/events/{ev['id']}", json={"title": "Rock Night Live"}, headers={"If-Match": "1"})
    body = r.json()
    assert body["title"] == "Rock Night Live"
    assert body["venue"] == ev["venue"]
    assert body["capacity"] == ev["capacity"]


@pytest.mark.parametrize("body", [{}, {"title": None}, {"status": "published"}])
async def test_patch_event_invalid_body_is_422(client, body):
    ev = await create_event(client)
    assert (await client.patch(f"/events/{ev['id']}", json=body, headers={"If-Match": "1"})).status_code == 422


async def test_patch_validates_merged_document(client):
    """Changing only capacity must still respect the existing tiers (quotas sum to 90)."""
    ev = await create_event(client)
    r = await client.patch(f"/events/{ev['id']}", json={"capacity": 50}, headers={"If-Match": "1"})
    assert r.status_code == 422


async def test_patch_start_after_existing_end_is_422(client):
    ev = await create_event(client)
    r = await client.patch(f"/events/{ev['id']}", json={"starts_at": future(days=30).isoformat()},
                           headers={"If-Match": "1"})
    assert r.status_code == 422


async def test_patch_start_and_end_together(client):
    ev = await create_event(client)
    start = future(days=30)
    r = await client.patch(
        f"/events/{ev['id']}",
        json={"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=3)).isoformat()},
        headers={"If-Match": "1"},
    )
    assert r.status_code == 200


async def test_patch_tiers_allowed_in_draft(client):
    ev = await create_event(client)
    tiers = [{"name": "Gold", "price_inr": 3000, "quota": 20}]
    r = await client.patch(f"/events/{ev['id']}", json={"ticket_tiers": tiers}, headers={"If-Match": "1"})
    assert r.status_code == 200
    assert tier_remaining(r.json(), "Gold") == 20


async def test_tiers_locked_after_publish(client):
    ev = await create_event(client, publish=True)  # version is now 2
    url = f"/events/{ev['id']}"
    tiers = [{"name": "Gold", "price_inr": 3000, "quota": 20}]

    r = await client.patch(url, json={"ticket_tiers": tiers}, headers={"If-Match": str(ev["version"])})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EVENT_LOCKED"

    r = await client.patch(url, json={"capacity": 200}, headers={"If-Match": str(ev["version"])})
    assert r.status_code == 409

    r = await client.patch(url, json={"title": "Still editable"}, headers={"If-Match": str(ev["version"])})
    assert r.status_code == 200


async def test_cancelled_event_cannot_be_edited(client):
    ev = await create_event(client)
    cancelled = (await client.post(f"/events/{ev['id']}/cancel")).json()
    r = await client.patch(f"/events/{ev['id']}", json={"title": "Too late"},
                           headers={"If-Match": str(cancelled["version"])})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EVENT_LOCKED"


# ---------- DELETE /events/{id} ----------

async def test_delete_draft(client):
    ev = await create_event(client)
    assert (await client.delete(f"/events/{ev['id']}")).status_code == 204
    assert (await client.get(f"/events/{ev['id']}")).status_code == 404


async def test_cannot_delete_published_event(client):
    ev = await create_event(client, publish=True)
    r = await client.delete(f"/events/{ev['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ILLEGAL_TRANSITION"


async def test_delete_missing_event_is_404(client):
    assert (await client.delete(f"/events/{MISSING_ID}")).status_code == 404


# ---------- Lifecycle (R1.6) ----------

async def test_publish_bumps_version(client):
    ev = await create_event(client)
    r = await client.post(f"/events/{ev['id']}/publish")
    assert r.status_code == 200
    assert r.json()["status"] == "published"
    assert r.json()["version"] == 2


async def test_publish_twice_is_409(client):
    ev = await create_event(client, publish=True)
    r = await client.post(f"/events/{ev['id']}/publish")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ILLEGAL_TRANSITION"


async def test_cannot_publish_past_event(client):
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    ev = await create_event(client, starts_at=start, ends_at=start + timedelta(hours=2))  # creating is allowed
    assert (await client.post(f"/events/{ev['id']}/publish")).status_code == 409


async def test_complete_before_end_is_409(client):
    ev = await create_event(client, publish=True)
    assert (await client.post(f"/events/{ev['id']}/complete")).status_code == 409


async def test_complete_after_end(client):
    ev = await create_event(client, publish=True)
    now = datetime.now(UTC)
    await db_set_event_times(ev["id"], now - timedelta(hours=3), now - timedelta(hours=1))
    r = await client.post(f"/events/{ev['id']}/complete")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


async def test_complete_draft_is_409(client):
    ev = await create_event(client)
    assert (await client.post(f"/events/{ev['id']}/complete")).status_code == 409


async def test_cancel_draft_and_published(client):
    draft = await create_event(client)
    published = await create_event(client, publish=True)
    for ev in (draft, published):
        r = await client.post(f"/events/{ev['id']}/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"


async def test_cancel_twice_is_409(client):
    ev = await create_event(client)
    await client.post(f"/events/{ev['id']}/cancel")
    assert (await client.post(f"/events/{ev['id']}/cancel")).status_code == 409


async def test_cannot_cancel_started_event(client):
    ev = await create_event(client, publish=True)
    now = datetime.now(UTC)
    await db_set_event_times(ev["id"], now - timedelta(hours=1), now + timedelta(hours=2))
    assert (await client.post(f"/events/{ev['id']}/cancel")).status_code == 409


@pytest.mark.parametrize("action", ["publish", "complete", "cancel"])
async def test_lifecycle_on_missing_event_is_404(client, action):
    assert (await client.post(f"/events/{MISSING_ID}/{action}")).status_code == 404


# ---------- GET /events (R1.3) ----------

async def test_pagination_with_tied_start_times_returns_each_once(client):
    """25 events in groups of 5 sharing the same starts_at: the cursor's tie-breaker must not skip or repeat."""
    org = await create_user(client, role="organizer")
    created = []
    base = future(days=10)  # computed once so tied times are exactly equal
    for i in range(25):
        start = base + timedelta(days=i // 5)  # 5 events per identical start time
        r = await client.post("/events", json=event_body(org["id"], title=f"Event number {i}", starts_at=start))
        created.append(r.json()["id"])

    seen, starts, cursor = [], [], None
    while True:
        params = {"limit": 7, **({"cursor": cursor} if cursor else {})}
        body = (await client.get("/events", params=params)).json()
        seen += [e["id"] for e in body["items"]]
        starts += [e["starts_at"] for e in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == 25
    assert set(seen) == set(created)
    parsed = [datetime.fromisoformat(s) for s in starts]
    assert parsed == sorted(parsed)  # ordered by start time


async def test_filter_by_status(client):
    org = await create_user(client, role="organizer")
    await create_event(client, org["id"])
    await create_event(client, org["id"], publish=True)
    body = (await client.get("/events", params={"status": "published"})).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "published"


async def test_city_filter_is_case_insensitive(client):
    """Requires the city_key fix."""
    org = await create_user(client, role="organizer")
    await create_event(client, org["id"])  # Pune
    await create_event(client, org["id"], venue={"name": "Hall", "city": "Mumbai"})
    for city in ["Pune", "pune", "PUNE", "  pune  "]:
        items = (await client.get("/events", params={"city": city})).json()["items"]
        assert len(items) == 1, city
        assert items[0]["venue"]["city"] == "Pune"


async def test_text_search_on_title(client):
    org = await create_user(client, role="organizer")
    await create_event(client, org["id"], title="Rock Night")
    await create_event(client, org["id"], title="Jazz Evening")
    items = (await client.get("/events", params={"q": "jazz"})).json()["items"]
    assert [e["title"] for e in items] == ["Jazz Evening"]


async def test_date_range_filter(client):
    org = await create_user(client, role="organizer")
    await create_event(client, org["id"], title="Soon event", starts_at=future(days=2))
    await create_event(client, org["id"], title="Later event", starts_at=future(days=20))
    params = {"starts_from": future(days=10).isoformat()}
    items = (await client.get("/events", params=params)).json()["items"]
    assert [e["title"] for e in items] == ["Later event"]


@pytest.mark.parametrize("params", [
    {"cursor": "abc"},
    {"status": "live"},
    {"q": "a"},
    {"limit": 0},
    {"starts_from": "2026-12-01T00:00:00"},  # no timezone
])
async def test_list_events_bad_params_are_422(client, params):
    assert (await client.get("/events", params=params)).status_code == 422


async def test_invalid_cursor_error_code(client):
    r = await client.get("/events", params={"cursor": "abc"})
    assert r.json()["error"]["code"] == "INVALID_CURSOR"