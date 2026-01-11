from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg
from psycopg_pool import AsyncConnectionPool

from subflow.config import Settings


class DatabasePool:
    """Singleton connection pool manager."""

    _pool: AsyncConnectionPool | None = None

    @classmethod
    async def get_pool(cls, settings: Settings) -> AsyncConnectionPool:
        if cls._pool is None:
            cls._pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=2,
                max_size=10,
                open=False,
            )
            await cls._pool.open()
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        if cls._pool is not None:
            await cls._pool.close()
            cls._pool = None


class BaseRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        async with self.pool.connection() as conn:
            yield conn
