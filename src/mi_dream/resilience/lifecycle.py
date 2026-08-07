"""Neo4j driver lifecycle — explicit start/close/health for long-running apps."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from neo4j import AsyncGraphDatabase

from mi_dream.config import settings


@dataclass
class Neo4jHealth:
    connected: bool
    database: str = ""
    error: str | None = None


class DriverLifecycle:
    """Explicit lifecycle for the Neo4j driver.

    Replaces the implicit module-level singleton with a managed instance.
    The old ``get_driver()`` remains as fallback for internal code that
    hasn't been migrated yet.
    """

    def __init__(self):
        self._driver: AsyncGraphDatabase | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._driver is None:
                self._driver = AsyncGraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                    notifications_disabled_classifications=["UNRECOGNIZED"],
                )
                await self._driver.verify_connectivity()

    async def close(self) -> None:
        async with self._lock:
            if self._driver is not None:
                await self._driver.close()
                self._driver = None

    async def health(self) -> Neo4jHealth:
        if self._driver is None:
            return Neo4jHealth(connected=False, database=settings.neo4j_database)
        try:
            async with self._driver.session(database=settings.neo4j_database) as session:
                await session.run("RETURN 1")
            return Neo4jHealth(connected=True, database=settings.neo4j_database)
        except Exception as exc:
            return Neo4jHealth(connected=False, database=settings.neo4j_database, error=str(exc))

    def get_driver(self) -> AsyncGraphDatabase:
        if self._driver is None:
            raise RuntimeError("Neo4j driver not started. Call await lifecycle.start() first.")
        return self._driver


# Global singleton — instantiated by the app at startup.
lifecycle = DriverLifecycle()
