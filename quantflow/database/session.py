"""Database engine and async session management for QuantFlow."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from quantflow.config.manager import ConfigManager
from quantflow.core.logging import get_logger
from quantflow.database.models import Base

logger = get_logger("database_session")


class DatabaseManager:
    """Manages SQLAlchemy async engine and session factory lifecycle."""

    def __init__(
        self,
        database_url: str = "sqlite+aiosqlite:///:memory:",
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> None:
        self.database_url = database_url

        # SQLite does not support pool_size / max_overflow
        engine_kwargs: dict[str, object] = {"echo": echo}
        if not database_url.startswith("sqlite"):
            engine_kwargs["pool_size"] = pool_size
            engine_kwargs["max_overflow"] = max_overflow

        self.engine: AsyncEngine = create_async_engine(
            database_url, **engine_kwargs
        )
        self.session_factory: async_sessionmaker[AsyncSession] = (
            async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        )

    @classmethod
    def from_config(
        cls, config: ConfigManager | None = None
    ) -> DatabaseManager:
        """Create DatabaseManager from application configuration."""
        cfg = config if config is not None else ConfigManager()
        url = str(
            cfg.get("database.url", "sqlite+aiosqlite:///:memory:")
        )
        echo = bool(cfg.get("database.echo", False))
        pool_size = int(cfg.get("database.pool_size", 10))
        max_overflow = int(cfg.get("database.max_overflow", 20))
        return cls(
            database_url=url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a transactional async session scope."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def create_all(self) -> None:
        """Create all tables defined in metadata."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully")

    async def drop_all(self) -> None:
        """Drop all tables defined in metadata."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.info("Database tables dropped successfully")

    async def close(self) -> None:
        """Dispose of the database engine and connection pools."""
        await self.engine.dispose()
        logger.info("Database engine disposed")
