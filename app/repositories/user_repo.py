from datetime import UTC, datetime
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from app.repositories.common import to_out

# def to_out(doc: dict | None) -> dict | None:
#     if doc is None:
#         return None
#     doc["id"] = str(doc.pop("_id"))
#     return doc


class UserRepository:
    def __init__(self, db: AsyncDatabase):
        self.col = db["users"]

    async def get_by_email(self, email: str) -> dict | None:
        return to_out(await self.col.find_one({"email": email}))

    async def insert(self, data: dict) -> dict:
        now = datetime.now(UTC)
        doc = {**data, "is_active": True, "created_at": now, "updated_at": now}
        await self.col.insert_one(doc)  # adds _id to doc in place
        return to_out(doc)

    async def get(self, user_id: str) -> dict | None:
        return to_out(await self.col.find_one({"_id": ObjectId(user_id)}))

    async def list_page(self, limit: int, after: str | None) -> list[dict]:
        query = {"_id": {"$gt": ObjectId(after)}} if after else {}
        cursor = self.col.find(query).sort("_id", 1).limit(limit)
        return [to_out(d) async for d in cursor]

    async def update(self, user_id: str, changes: dict) -> dict | None:
        changes = {**changes, "updated_at": datetime.now(UTC)}
        doc = await self.col.find_one_and_update(
            {"_id": ObjectId(user_id)}, {"$set": changes},
            return_document=ReturnDocument.AFTER,
        )
        return to_out(doc)