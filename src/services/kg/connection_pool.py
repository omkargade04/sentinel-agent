"""
Neo4j Connection Pool Manager

Provides connection pooling, health monitoring, and connection lifecycle
management for improved performance and reliability.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional

from neo4j import AsyncDriver, AsyncSession, GraphDatabase
from pydantic import BaseModel, Field

from src.utils.logging import get_logger

logger = get_logger(__name__)


class Neo4jPoolConfig(BaseModel):
    """Configuration for Neo4j connection pool."""

    # Connection settings
    uri: str = Field(..., description="Neo4j connection URI")
    username: str = Field(..., description="Neo4j username")
    password: str = Field(..., description="Neo4j password")
    database: str = Field(default="neo4j", description="Neo4j database name")

    # Pool settings
    max_connection_lifetime: int = Field(
        default=3600,  # 1 hour
        description="Maximum connection lifetime in seconds",
        ge=60,
        le=86400
    )
    max_connection_pool_size: int = Field(
        default=100,
        description="Maximum number of connections in pool",
        ge=1,
        le=1000
    )
    connection_acquisition_timeout: int = Field(
        default=60,
        description="Connection acquisition timeout in seconds",
        ge=1,
        le=300
    )

    # Health check settings
    health_check_interval: int = Field(
        default=30,
        description="Health check interval in seconds",
        ge=5,
        le=300
    )
    max_transaction_retry_time: int = Field(
        default=30,
        description="Maximum transaction retry time in seconds",
        ge=1,
        le=180
    )


@dataclass
class ConnectionStats:
    """Connection pool statistics."""
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    failed_connections: int = 0
    total_queries: int = 0
    failed_queries: int = 0
    avg_query_time_ms: float = 0.0
    last_health_check: Optional[float] = None
    is_healthy: bool = True


class Neo4jConnectionPool:
    """
    Neo4j connection pool with health monitoring and lifecycle management.

    Provides:
    - Connection pooling with configurable limits
    - Health monitoring and automatic recovery
    - Query performance tracking
    - Graceful degradation on connection failures

    Usage:
        config = Neo4jPoolConfig(uri="bolt://localhost:7687", ...)
        pool = Neo4jConnectionPool(config)
        await pool.initialize()

        async with pool.get_session() as session:
            result = await session.run("MATCH (n) RETURN count(n)")
    """

    def __init__(self, config: Neo4jPoolConfig):
        self._config = config
        self._driver: Optional[AsyncDriver] = None
        self._stats = ConnectionStats()
        self._health_check_task: Optional[asyncio.Task] = None
        self._query_times: list[float] = []
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the connection pool and start health monitoring."""
        if self._initialized:
            return

        try:
            logger.info(f"Initializing Neo4j connection pool to {self._config.uri}")

            # Create driver with connection pool settings
            self._driver = GraphDatabase.async_driver(
                self._config.uri,
                auth=(self._config.username, self._config.password),
                max_connection_lifetime=self._config.max_connection_lifetime,
                max_connection_pool_size=self._config.max_connection_pool_size,
                connection_acquisition_timeout=self._config.connection_acquisition_timeout,
                max_transaction_retry_time=self._config.max_transaction_retry_time,
            )

            # Verify connectivity
            await self._verify_connectivity()

            # Start health monitoring
            self._health_check_task = asyncio.create_task(self._health_check_loop())

            self._initialized = True
            logger.info("Neo4j connection pool initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Neo4j connection pool: {e}", exc_info=True)
            await self.close()
            raise

    async def close(self) -> None:
        """Close the connection pool and cleanup resources."""
        logger.info("Closing Neo4j connection pool")

        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Close driver
        if self._driver:
            await self._driver.close()
            self._driver = None

        self._initialized = False
        logger.info("Neo4j connection pool closed")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session from the pool.

        Returns:
            AsyncSession: Neo4j session for executing queries

        Raises:
            RuntimeError: If pool is not initialized
            Exception: If session acquisition fails
        """
        if not self._initialized or not self._driver:
            raise RuntimeError("Connection pool not initialized")

        start_time = time.time()
        session = None

        try:
            session = self._driver.session(database=self._config.database)
            self._stats.active_connections += 1
            yield session

        except Exception as e:
            self._stats.failed_connections += 1
            logger.error(f"Session error: {e}", exc_info=True)
            raise

        finally:
            if session:
                await session.close()
                self._stats.active_connections -= 1

            # Track query time
            query_time = (time.time() - start_time) * 1000
            self._query_times.append(query_time)

            # Keep only recent query times for average calculation
            if len(self._query_times) > 100:
                self._query_times = self._query_times[-100:]

            self._stats.avg_query_time_ms = sum(self._query_times) / len(self._query_times)
            self._stats.total_queries += 1

    async def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> list[Dict[str, Any]]:
        """
        Execute a query and return results.

        Args:
            query: Cypher query string
            parameters: Query parameters
            timeout: Query timeout in seconds

        Returns:
            List of result records as dictionaries

        Raises:
            Exception: If query execution fails
        """
        async with self.get_session() as session:
            try:
                if timeout:
                    result = await asyncio.wait_for(
                        session.run(query, parameters or {}),
                        timeout=timeout
                    )
                else:
                    result = await session.run(query, parameters or {})

                records = [dict(record) async for record in result]
                return records

            except asyncio.TimeoutError:
                self._stats.failed_queries += 1
                logger.error(f"Query timeout after {timeout}s: {query[:100]}...")
                raise

            except Exception as e:
                self._stats.failed_queries += 1
                logger.error(f"Query execution failed: {e}", exc_info=True)
                raise

    async def _verify_connectivity(self) -> None:
        """Verify database connectivity during initialization."""
        try:
            async with self.get_session() as session:
                await session.run("RETURN 1 AS test")
            logger.debug("Neo4j connectivity verified")

        except Exception as e:
            logger.error(f"Neo4j connectivity check failed: {e}")
            raise

    async def _health_check_loop(self) -> None:
        """Continuous health monitoring loop."""
        while True:
            try:
                await asyncio.sleep(self._config.health_check_interval)
                await self._perform_health_check()

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"Health check failed: {e}", exc_info=True)
                self._stats.is_healthy = False

    async def _perform_health_check(self) -> None:
        """Perform health check and update statistics."""
        try:
            start_time = time.time()

            async with self.get_session() as session:
                # Simple health check query
                await session.run("RETURN 1 AS health_check")

            # Update health statistics
            self._stats.last_health_check = time.time()
            self._stats.is_healthy = True

            health_check_time = (time.time() - start_time) * 1000
            logger.debug(f"Health check completed in {health_check_time:.1f}ms")

        except Exception as e:
            self._stats.is_healthy = False
            logger.warning(f"Health check failed: {e}")

    def get_stats(self) -> ConnectionStats:
        """Get current connection pool statistics."""
        return self._stats

    def is_healthy(self) -> bool:
        """Check if the connection pool is healthy."""
        return self._stats.is_healthy and self._initialized

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# Global connection pool instance
_connection_pool: Optional[Neo4jConnectionPool] = None


async def get_connection_pool() -> Neo4jConnectionPool:
    """
    Get the global connection pool instance.

    Returns:
        Neo4jConnectionPool: Initialized connection pool

    Raises:
        RuntimeError: If pool is not initialized
    """
    global _connection_pool

    if _connection_pool is None or not _connection_pool.is_healthy():
        raise RuntimeError("Neo4j connection pool not initialized or unhealthy")

    return _connection_pool


async def initialize_connection_pool(config: Neo4jPoolConfig) -> None:
    """
    Initialize the global connection pool.

    Args:
        config: Neo4j pool configuration
    """
    global _connection_pool

    if _connection_pool:
        await _connection_pool.close()

    _connection_pool = Neo4jConnectionPool(config)
    await _connection_pool.initialize()


async def close_connection_pool() -> None:
    """Close the global connection pool."""
    global _connection_pool

    if _connection_pool:
        await _connection_pool.close()
        _connection_pool = None