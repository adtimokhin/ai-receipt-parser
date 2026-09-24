"""Proves the db_mongodb overlay is wired into the running app (overlay-contract 7).

Mock mode (default): ``init_client`` is replaced with a spec'd AsyncMock, so no
socket is opened and the ``ping`` path is exercised offline. Integration mode
(``tests_integration``): a real MongoDB container backs it.
"""

from __future__ import annotations

from pymongo import AsyncMongoClient

from receipt_parser_backend.db.mongodb.client import get_client
from receipt_parser_backend.health import check_db_mongodb
from receipt_parser_backend.lifespan import lifespan
from receipt_parser_backend.main import app


async def test_db_mongodb_boots(mongodb_db: object) -> None:
    async with lifespan(app):
        client = getattr(app.state, "db_mongodb", None)
        assert client is not None, "db_mongodb client missing from app.state"
        assert isinstance(client, AsyncMongoClient)
        assert client is get_client()

        result = await check_db_mongodb()
        assert result.healthy, result
