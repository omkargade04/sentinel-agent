"""
KG Service Initialization and Factory

Provides factory methods and initialization utilities for KG services
with optimized connection pooling and monitoring.
"""

from __future__ import annotations

from typing import Optional

from src.core.pr_review_config import pr_review_settings
from src.services.kg.connection_pool import (
    Neo4jConnectionPool,
    Neo4jPoolConfig,
    initialize_connection_pool
)
from src.services.kg.performance_monitor import initialize_performance_monitor
from src.services.kg.kg_query_service import KGQueryService
from src.utils.logging import get_logger

logger = get_logger(__name__)


class KGServiceFactory:
    """
    Factory for creating and initializing optimized KG services.

    Handles setup of:
    - Neo4j connection pooling
    - Performance monitoring
    - Service dependencies
    """

    @classmethod
    async def create_optimized_kg_service(
        cls,
        enable_monitoring: bool = True
    ) -> KGQueryService:
        """
        Create a fully optimized KG Query Service with connection pooling and monitoring.

        Args:
            enable_monitoring: Whether to enable performance monitoring

        Returns:
            Optimized KGQueryService instance

        Raises:
            Exception: If initialization fails
        """
        logger.info("Initializing optimized KG Query Service...")

        try:
            # Initialize performance monitoring first
            if enable_monitoring:
                initialize_performance_monitor(max_history=10000)
                logger.info("Performance monitoring initialized")

            # Initialize Neo4j connection pool
            neo4j_config = Neo4jPoolConfig(
                uri=pr_review_settings.neo4j_uri,
                username=pr_review_settings.neo4j_username,
                password=pr_review_settings.neo4j_password,
                database=pr_review_settings.neo4j_database,
                max_connection_pool_size=pr_review_settings.neo4j_max_pool_size,
                max_connection_lifetime=pr_review_settings.neo4j_max_connection_lifetime,
                connection_acquisition_timeout=pr_review_settings.timeouts.neo4j_connection_timeout,
            )

            await initialize_connection_pool(neo4j_config)
            logger.info("Neo4j connection pool initialized")

            # Create KG Query Service (no direct driver needed - uses connection pool)
            kg_service = KGQueryService(
                driver=None,  # Uses connection pool
                database=pr_review_settings.neo4j_database
            )

            logger.info("Optimized KG Query Service created successfully")
            return kg_service

        except Exception as e:
            logger.error(f"Failed to initialize optimized KG service: {e}", exc_info=True)
            raise

    @classmethod
    async def create_legacy_kg_service(
        cls,
        neo4j_driver=None
    ) -> KGQueryService:
        """
        Create legacy KG Query Service for backward compatibility.

        Args:
            neo4j_driver: Direct Neo4j driver instance

        Returns:
            KGQueryService with legacy configuration
        """
        logger.warning("Creating legacy KG Query Service without optimizations")

        if neo4j_driver is None:
            raise ValueError("neo4j_driver is required for legacy mode")

        return KGQueryService(
            driver=neo4j_driver,
            database=pr_review_settings.neo4j_database
        )

    @classmethod
    async def health_check(cls) -> dict[str, bool]:
        """
        Perform health check on all KG service components.

        Returns:
            Dictionary with health status of each component
        """
        from src.services.kg.connection_pool import get_connection_pool
        from src.services.kg.performance_monitor import get_performance_monitor

        health_status = {}

        try:
            # Check connection pool
            pool = await get_connection_pool()
            health_status["connection_pool"] = pool.is_healthy() if pool else False
        except Exception as e:
            logger.error(f"Connection pool health check failed: {e}")
            health_status["connection_pool"] = False

        try:
            # Check performance monitor
            monitor = get_performance_monitor()
            monitor_health = monitor.get_health_status()
            health_status["performance_monitor"] = monitor_health["is_healthy"]
        except Exception as e:
            logger.error(f"Performance monitor health check failed: {e}")
            health_status["performance_monitor"] = False

        return health_status

    @classmethod
    async def get_performance_summary(cls) -> dict:
        """
        Get comprehensive performance summary from all components.

        Returns:
            Dictionary with performance metrics
        """
        from src.services.kg.connection_pool import get_connection_pool
        from src.services.kg.performance_monitor import get_performance_monitor

        summary = {}

        try:
            # Connection pool stats
            pool = await get_connection_pool()
            if pool:
                summary["connection_pool"] = pool.get_stats()
        except Exception as e:
            logger.error(f"Failed to get connection pool stats: {e}")

        try:
            # Performance monitor stats
            monitor = get_performance_monitor()
            summary["performance"] = {
                "overall_stats": monitor.get_overall_stats(),
                "health_status": monitor.get_health_status(),
                "slow_queries": monitor.get_top_slow_queries(5)
            }
        except Exception as e:
            logger.error(f"Failed to get performance stats: {e}")

        return summary


async def initialize_kg_services(
    enable_monitoring: bool = True
) -> KGQueryService:
    """
    Initialize all KG services with optimizations.

    Args:
        enable_monitoring: Whether to enable performance monitoring

    Returns:
        Optimized KGQueryService instance
    """
    return await KGServiceFactory.create_optimized_kg_service(
        enable_monitoring=enable_monitoring
    )


async def cleanup_kg_services() -> None:
    """
    Cleanup all KG services and close connections.
    """
    from src.services.kg.connection_pool import close_connection_pool

    try:
        await close_connection_pool()
        logger.info("Neo4j connection pool closed")
    except Exception as e:
        logger.error(f"Failed to close connection pool: {e}")

    logger.info("KG services cleanup completed")