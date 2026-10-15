"""Integration tests validating live PostgreSQL and Redis services in Docker."""

from __future__ import annotations

import os
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_postgres_live_connection_and_migrations() -> None:
    """Validate connection to live PostgreSQL and ensure Alembic migrations ran."""
    postgres_host = os.environ.get("POSTGRES_HOST")
    if not postgres_host:
        pytest.skip("POSTGRES_HOST not configured; skipping live database test")

    from quantflow.database.session import DatabaseManager

    db_manager = DatabaseManager.from_config()
    try:
        async with db_manager.session() as session:
            # 1. Verify basic query execution
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

            # 2. Verify alembic migration version table exists and has revision
            ver_res = await session.execute(text("SELECT version_num FROM alembic_version"))
            version_num = ver_res.scalar()
            assert version_num is not None, "Alembic migrations did not apply to Postgres!"
            assert "001" in str(version_num) or len(str(version_num)) > 0
    finally:
        await db_manager.close()


@pytest.mark.asyncio
async def test_redis_live_connection() -> None:
    """Validate connection and basic operations against live Redis."""
    redis_host = os.environ.get("REDIS_HOST")
    if not redis_host:
        pytest.skip("REDIS_HOST not configured; skipping live Redis test")

    import redis.asyncio as aioredis

    port = int(os.environ.get("REDIS_PORT", 6379))
    db = int(os.environ.get("REDIS_DB", 0))
    password = os.environ.get("REDIS_PASSWORD") or None

    client = aioredis.Redis(
        host=redis_host,
        port=port,
        db=db,
        password=password,
        decode_responses=True,
    )
    try:
        # 1. Ping
        assert await client.ping() is True

        # 2. Write / Read / Delete
        test_key = "quantflow:docker:test_key"
        await client.set(test_key, "hello_quantflow", ex=60)
        val = await client.get(test_key)
        assert val == "hello_quantflow"
        await client.delete(test_key)
    finally:
        await client.aclose()
