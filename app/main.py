from contextlib import asynccontextmanager
from fastapi import FastAPI
from pymongo import AsyncMongoClient
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.middleware import RequestIDMiddleware
from app.db import client as db
from app.db.indexes import create_indexes
from app.routers import users,bookings,events
from app.routers import auth, bookings, events, users

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.client = AsyncMongoClient(settings.mongo_uri, tz_aware=True)  # datetimes come back with UTC tzinfo
    await create_indexes(db.get_db())
    yield
    await db.client.close()


app = FastAPI(title="TicketHub", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)
app.include_router(users.router)
app.include_router(bookings.router)
app.include_router(events.router)
app.include_router(auth.router)



@app.get("/health")
async def health():
    await db.get_db().command("ping")
    return {"status": "ok"}