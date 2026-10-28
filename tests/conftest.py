import os

os.environ["MONGO_DB"] = "tickethub_test"  # must be set before the app imports settings

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import client as db
from app.main import app


@pytest.fixture
async def client():
    """A fresh HTTP client per test, with the app's startup/shutdown run and all data cleared."""
    async with app.router.lifespan_context(app):  # httpx doesn't run lifespan by itself
        database = db.get_db()
        for name in await database.list_collection_names():
            await database[name].delete_many({})  # clear data, keep indexes
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c