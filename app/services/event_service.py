from datetime import UTC, datetime
from app.core.errors import AppError, NotFound
from app.core.pagination import decode_cursor, encode_cursor
from app.models.common import Page
from app.models.event import EventCreate, EventRead, EventStatus, EventUpdate, validate_event_shape
from app.repositories.event_repo import EventRepository
from app.core.text import normalize_city

LOCKED_AFTER_DRAFT = {"capacity", "ticket_tiers"}


class EventService:
    def __init__(self, repo: EventRepository):
        self.repo = repo

    async def create(self, data: EventCreate) -> EventRead:
        return EventRead(**await self.repo.insert(data.model_dump()))

    async def get(self, event_id: str) -> EventRead:
        doc = await self.repo.get(event_id)
        if not doc:
            raise NotFound("Event")
        return EventRead(**doc)

    async def list_page(self, *, city, status, starts_from, starts_to, q, limit, cursor) -> Page[EventRead]:
        filters: dict = {}
        if city:
            # filters["venue.city"] = city
            filters["city_key"] = normalize_city(city)
        if status:
            filters["status"] = status
        date_range = {}
        if starts_from:
            date_range["$gte"] = starts_from
        if starts_to:
            date_range["$lt"] = starts_to
        if date_range:
            filters["starts_at"] = date_range
        if q:
            filters["$text"] = {"$search": q}

        after = decode_cursor(cursor) if cursor else None
        docs = await self.repo.list_page(filters, limit + 1, after)
        has_more = len(docs) > limit
        docs = docs[:limit]
        next_cursor = encode_cursor(docs[-1]["starts_at"], docs[-1]["id"]) if has_more else None
        return Page(items=[EventRead(**d) for d in docs], next_cursor=next_cursor)

    async def update(self, event_id: str, expected_version: int, data: EventUpdate) -> EventRead:
        current = await self.repo.get(event_id)
        if not current:
            raise NotFound("Event")
        if current["version"] != expected_version:
            raise AppError(409, "VERSION_CONFLICT", "Event was modified; refetch and retry")
        if current["status"] in (EventStatus.completed, EventStatus.cancelled):
            raise AppError(409, "EVENT_LOCKED", "Finished events cannot be edited")

        changes = data.model_dump(exclude_unset=True)
        if current["status"] != EventStatus.draft and changes.keys() & LOCKED_AFTER_DRAFT:
            raise AppError(409, "EVENT_LOCKED", "capacity and ticket_tiers can only change in draft")

        merged = {**current, **changes}
        try:
            validate_event_shape(merged["starts_at"], merged["ends_at"],
                                 merged["capacity"], merged["ticket_tiers"])
        except ValueError as e:
            raise AppError(422, "VALIDATION_ERROR", str(e))

        if "ticket_tiers" in changes:
            changes["ticket_tiers"] = [{**t, "remaining": t["quota"]} for t in changes["ticket_tiers"]]

        doc = await self.repo.update_versioned(event_id, expected_version, changes)
        if not doc:  # someone else wrote between our read and our write
            raise AppError(409, "VERSION_CONFLICT", "Event was modified; refetch and retry")
        return EventRead(**doc)

    async def delete(self, event_id: str) -> None:
        if await self.repo.delete_draft(event_id):
            return
        if not await self.repo.get(event_id):
            raise NotFound("Event")
        raise AppError(409, "ILLEGAL_TRANSITION", "Only drafts can be deleted; cancel published events")

    # ---- lifecycle (R1.6) ----

    async def publish(self, event_id: str) -> EventRead:
        return await self._transition(event_id, EventStatus.draft, EventStatus.published,
                                      {"starts_at": {"$gt": datetime.now(UTC)}})

    async def complete(self, event_id: str) -> EventRead:
        return await self._transition(event_id, EventStatus.published, EventStatus.completed,
                                      {"ends_at": {"$lte": datetime.now(UTC)}})

    async def cancel(self, event_id: str) -> EventRead:
        current = await self.get(event_id)
        if current.status not in (EventStatus.draft, EventStatus.published):
            raise AppError(409, "ILLEGAL_TRANSITION", f"Cannot cancel a {current.status} event")
        event = await self._transition(event_id, current.status, EventStatus.cancelled,
                                       {"starts_at": {"$gt": datetime.now(UTC)}})
        # Phase 5: enqueue the refund job for confirmed bookings here (R3.7)
        return event

    async def _transition(self, event_id, from_status, to_status, guard) -> EventRead:
        doc = await self.repo.set_status(event_id, from_status, to_status, guard)
        if doc:
            return EventRead(**doc)
        if not await self.repo.get(event_id):
            raise NotFound("Event")
        raise AppError(409, "ILLEGAL_TRANSITION", f"Cannot move event to {to_status} from its current state")