from pymongo.asynchronous.database import AsyncDatabase

async def create_indexes(db: AsyncDatabase) -> None:
    await db["users"].create_index("email", unique=True)

    await db["events"].create_index([("status", 1), ("starts_at", 1)])   # R1.4: filtered listing
    await db["events"].create_index([("starts_at", 1), ("_id", 1)])      # cursor sort
    await db["events"].create_index([("title", "text")])                 # R1.4: q search
    await db["events"].create_index([("city_key", 1), ("starts_at", 1)])

    await db["bookings"].create_index([("status", 1), ("hold_expires_at", 1)])  # R1.4: expiry cron
    await db["bookings"].create_index([("event_id", 1), ("status", 1)])         # bookings per event
    await db["bookings"].create_index("user_id")                                # "my bookings"