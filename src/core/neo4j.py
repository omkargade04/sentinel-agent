"""Neo4j connection utilities.

This module mirrors the role of `src/core/database.py` for Postgres.
We keep Neo4j driver lifecycle management here so services can depend on a single,
well-defined place for graph DB connectivity.
"""

from __future__ import annotations

import threading

from neo4j import AsyncDriver, AsyncGraphDatabase

from src.core.config import settings


class Neo4jConnection:
    """Singleton-style Neo4j driver manager."""

    _driver: AsyncDriver | None = None
    _lock = threading.Lock()

    @classmethod
    def get_driver(cls) -> AsyncDriver:
        """Return a cached Neo4j AsyncDriver, creating it if needed.
        
        Thread-safe: Uses a lock to prevent multiple driver instances
        from being created during concurrent initialization.
        """
        # Fast path: if driver already exists, return it without locking
        if cls._driver is not None:
            return cls._driver
        
        # Slow path: acquire lock and check again (double-checked locking)
        with cls._lock:
            # Check again inside lock (another thread may have created it)
            if cls._driver is None:
                if not settings.NEO4J_URI:
                    raise ValueError("NEO4J_URI is not configured")
                if not settings.NEO4J_USERNAME:
                    raise ValueError("NEO4J_USERNAME is not configured")
                if not settings.NEO4J_PASSWORD:
                    raise ValueError("NEO4J_PASSWORD is not configured")

                cls._driver = AsyncGraphDatabase.driver(
                    settings.NEO4J_URI,
                    auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
                    connection_timeout=60,
                    max_transaction_retry_time=60,
                    keep_alive=True,
                )
            return cls._driver

    @classmethod
    async def close_driver(cls) -> None:
        """Close the Neo4j driver, if open.
        
        Thread-safe: Uses a lock to prevent race conditions when closing
        the driver while other threads may be accessing it.
        """
        with cls._lock:
            if cls._driver is not None:
                await cls._driver.close()
                cls._driver = None


def get_neo4j_driver() -> AsyncDriver:
    """Convenience getter for services/activities."""

    return Neo4jConnection.get_driver()