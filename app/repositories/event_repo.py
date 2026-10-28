from datetime import UTC, datetime
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from app.repositories.common import to_out
from app.core.text import normalize_city


class EventRepository:
    def __init__(self, db: AsyncDatabase):
        self.col = db["events"]

    async def insert(self, data: dict) -> dict:
        now = datetime.now(UTC)
        doc = {
            **data,
            "organizer_id": ObjectId(data["organizer_id"]),
            "city_key": normalize_city(data["venue"]["city"]),
            "ticket_tiers": [{**t, "remaining": t["quota"]} for t in data["ticket_tiers"]],
            "status": "draft", "version": 1, "created_at": now, "updated_at": now,
        }
        await self.col.insert_one(doc)
        return to_out(doc)

    async def get(self, event_id: str) -> dict | None:
        return to_out(await self.col.find_one({"_id": ObjectId(event_id)}))

    async def list_page(self, filters: dict, limit: int,
                        after: tuple[datetime, str] | None) -> list[dict]:
        query = dict(filters)
        if after:
            starts_at, oid = after[0], ObjectId(after[1])
            query["$or"] = [
                {"starts_at": {"$gt": starts_at}},
                {"starts_at": starts_at, "_id": {"$gt": oid}},  # tie-breaker
            ]
        cursor = self.col.find(query).sort([("starts_at", 1), ("_id", 1)]).limit(limit)
        return [to_out(d) async for d in cursor]

    # async def update_versioned(self, event_id: str, version: int, changes: dict) -> dict | None:
    #     return to_out(await self.col.find_one_and_update(
    #         {"_id": ObjectId(event_id), "version": version},
    #         {"$set": {**changes, "updated_at": datetime.now(UTC)}, "$inc": {"version": 1}},
    #         return_document=ReturnDocument.AFTER,
    #     ))
    
    async def update_versioned(self, event_id: str, version: int, changes: dict) -> dict | None:
        if "venue" in changes:                                        # ← new
            changes = {**changes, "city_key": normalize_city(changes["venue"]["city"])}
        return to_out(await self.col.find_one_and_update(
            {"_id": ObjectId(event_id), "version": version},
            {"$set": {**changes, "updated_at": datetime.now(UTC)}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        ))

    async def set_status(self, event_id: str, from_status: str, to_status: str,
                         guard: dict | None = None) -> dict | None:
        return to_out(await self.col.find_one_and_update(
            {"_id": ObjectId(event_id), "status": from_status, **(guard or {})},
            {"$set": {"status": to_status, "updated_at": datetime.now(UTC)}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        ))

    async def delete_draft(self, event_id: str) -> bool:
        res = await self.col.delete_one({"_id": ObjectId(event_id), "status": "draft"})
        return res.deleted_count == 1

    # ---- seat counters (used by bookings) ----

    async def reserve_seats(self, event_id: str, tier: str, qty: int) -> bool:
        res = await self.col.update_one(
            {
                "_id": ObjectId(event_id),
                "status": "published",
                "starts_at": {"$gt": datetime.now(UTC)},
                "ticket_tiers": {"$elemMatch": {"name": tier, "remaining": {"$gte": qty}}},
            },
            {"$inc": {"ticket_tiers.$.remaining": -qty}},
        )
        return res.modified_count == 1

    async def release_seats(self, event_id: str, tier: str, qty: int) -> None:
        await self.col.update_one(
            {"_id": ObjectId(event_id), "ticket_tiers.name": tier},
            {"$inc": {"ticket_tiers.$.remaining": qty}},
        )