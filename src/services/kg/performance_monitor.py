"""
KG Performance Monitoring Service

Tracks performance metrics, query statistics, and health indicators
for the KG Query Service and related components.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from collections import defaultdict, deque

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class QueryMetric:
    """Individual query performance metric."""
    query_type: str
    execution_time_ms: float
    cache_hit: bool
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class PerformanceStats:
    """Aggregated performance statistics."""
    total_queries: int = 0
    total_errors: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    avg_query_time_ms: float = 0.0
    p95_query_time_ms: float = 0.0
    p99_query_time_ms: float = 0.0
    queries_per_second: float = 0.0
    error_rate_percent: float = 0.0
    cache_hit_rate_percent: float = 0.0


class KGPerformanceMonitor:
    """
    Performance monitoring service for KG operations.

    Features:
    - Real-time query performance tracking
    - Cache effectiveness monitoring
    - Error rate tracking and alerting
    - Performance trend analysis
    - Health check integration

    Usage:
        monitor = KGPerformanceMonitor()

        # Track a query
        with monitor.track_query("find_symbol") as tracker:
            result = await kg_service.find_symbol(...)
            tracker.set_cache_hit(True)
    """

    def __init__(self, max_metrics_history: int = 10000):
        """
        Initialize performance monitor.

        Args:
            max_metrics_history: Maximum number of metrics to keep in memory
        """
        self._max_history = max_metrics_history
        self._metrics: deque[QueryMetric] = deque(maxlen=max_metrics_history)
        self._query_type_stats: Dict[str, List[float]] = defaultdict(list)
        self._start_time = time.time()

    def track_query(self, query_type: str) -> "QueryTracker":
        """
        Create a query tracker for measuring performance.

        Args:
            query_type: Type of query being tracked

        Returns:
            QueryTracker context manager
        """
        return QueryTracker(self, query_type)

    def record_metric(self, metric: QueryMetric) -> None:
        """
        Record a query performance metric.

        Args:
            metric: Query metric to record
        """
        self._metrics.append(metric)

        # Update query type statistics
        if len(self._query_type_stats[metric.query_type]) > 1000:
            # Keep only recent metrics per query type
            self._query_type_stats[metric.query_type] = \
                self._query_type_stats[metric.query_type][-500:]

        self._query_type_stats[metric.query_type].append(metric.execution_time_ms)

        # Log slow queries
        if metric.execution_time_ms > 5000:  # 5 seconds
            logger.warning(
                f"Slow query detected: {metric.query_type} took {metric.execution_time_ms:.1f}ms"
            )

        # Log query errors
        if metric.error:
            logger.error(f"Query error in {metric.query_type}: {metric.error}")

    def get_overall_stats(self, window_minutes: Optional[int] = None) -> PerformanceStats:
        """
        Get overall performance statistics.

        Args:
            window_minutes: Time window for statistics (None for all time)

        Returns:
            Aggregated performance statistics
        """
        if window_minutes:
            cutoff_time = time.time() - (window_minutes * 60)
            metrics = [m for m in self._metrics if m.timestamp >= cutoff_time]
        else:
            metrics = list(self._metrics)

        if not metrics:
            return PerformanceStats()

        # Calculate basic statistics
        total_queries = len(metrics)
        total_errors = sum(1 for m in metrics if m.error)
        cache_hits = sum(1 for m in metrics if m.cache_hit)
        cache_misses = total_queries - cache_hits

        # Calculate timing statistics
        execution_times = [m.execution_time_ms for m in metrics]
        avg_time = sum(execution_times) / len(execution_times)
        sorted_times = sorted(execution_times)

        p95_index = int(0.95 * len(sorted_times))
        p99_index = int(0.99 * len(sorted_times))
        p95_time = sorted_times[p95_index] if p95_index < len(sorted_times) else 0
        p99_time = sorted_times[p99_index] if p99_index < len(sorted_times) else 0

        # Calculate rates
        time_window = window_minutes * 60 if window_minutes else (time.time() - self._start_time)
        qps = total_queries / max(time_window, 1)
        error_rate = (total_errors / total_queries * 100) if total_queries > 0 else 0
        cache_hit_rate = (cache_hits / total_queries * 100) if total_queries > 0 else 0

        return PerformanceStats(
            total_queries=total_queries,
            total_errors=total_errors,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            avg_query_time_ms=avg_time,
            p95_query_time_ms=p95_time,
            p99_query_time_ms=p99_time,
            queries_per_second=qps,
            error_rate_percent=error_rate,
            cache_hit_rate_percent=cache_hit_rate,
        )

    def get_query_type_stats(self, query_type: str) -> Dict[str, Any]:
        """
        Get statistics for a specific query type.

        Args:
            query_type: Query type to analyze

        Returns:
            Dictionary with query type statistics
        """
        if query_type not in self._query_type_stats:
            return {"error": "No data for query type"}

        times = self._query_type_stats[query_type]
        if not times:
            return {"error": "No timing data available"}

        sorted_times = sorted(times)
        return {
            "query_type": query_type,
            "total_queries": len(times),
            "avg_time_ms": sum(times) / len(times),
            "min_time_ms": min(times),
            "max_time_ms": max(times),
            "p50_time_ms": sorted_times[len(sorted_times) // 2],
            "p95_time_ms": sorted_times[int(0.95 * len(sorted_times))],
            "p99_time_ms": sorted_times[int(0.99 * len(sorted_times))],
        }

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get current health status of KG operations.

        Returns:
            Dictionary with health indicators
        """
        recent_stats = self.get_overall_stats(window_minutes=5)  # Last 5 minutes
        overall_stats = self.get_overall_stats()

        # Determine health status
        is_healthy = True
        issues = []

        # Check error rate
        if recent_stats.error_rate_percent > 5.0:
            is_healthy = False
            issues.append(f"High error rate: {recent_stats.error_rate_percent:.1f}%")

        # Check query performance
        if recent_stats.p95_query_time_ms > 10000:  # 10 seconds
            is_healthy = False
            issues.append(f"Slow queries: P95 = {recent_stats.p95_query_time_ms:.1f}ms")

        # Check cache effectiveness
        if recent_stats.total_queries > 10 and recent_stats.cache_hit_rate_percent < 30:
            issues.append(f"Low cache hit rate: {recent_stats.cache_hit_rate_percent:.1f}%")

        return {
            "is_healthy": is_healthy,
            "issues": issues,
            "recent_stats": {
                "queries_last_5min": recent_stats.total_queries,
                "avg_response_time_ms": recent_stats.avg_query_time_ms,
                "error_rate_percent": recent_stats.error_rate_percent,
                "cache_hit_rate_percent": recent_stats.cache_hit_rate_percent,
            },
            "overall_stats": {
                "total_queries": overall_stats.total_queries,
                "uptime_seconds": time.time() - self._start_time,
                "queries_per_second": overall_stats.queries_per_second,
            }
        }

    def get_top_slow_queries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get the slowest queries in recent history.

        Args:
            limit: Maximum number of slow queries to return

        Returns:
            List of slow query information
        """
        # Get recent metrics (last hour)
        cutoff_time = time.time() - 3600
        recent_metrics = [m for m in self._metrics if m.timestamp >= cutoff_time]

        # Sort by execution time and get top slow queries
        slow_queries = sorted(recent_metrics, key=lambda m: m.execution_time_ms, reverse=True)[:limit]

        return [
            {
                "query_type": m.query_type,
                "execution_time_ms": m.execution_time_ms,
                "timestamp": m.timestamp,
                "cache_hit": m.cache_hit,
                "error": m.error,
            }
            for m in slow_queries
        ]

    def clear_metrics(self) -> None:
        """Clear all stored metrics."""
        self._metrics.clear()
        self._query_type_stats.clear()
        self._start_time = time.time()
        logger.info("Performance metrics cleared")


class QueryTracker:
    """Context manager for tracking individual query performance."""

    def __init__(self, monitor: KGPerformanceMonitor, query_type: str):
        self._monitor = monitor
        self._query_type = query_type
        self._start_time: Optional[float] = None
        self._cache_hit = False
        self._error: Optional[str] = None

    def __enter__(self) -> "QueryTracker":
        """Start tracking the query."""
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Finish tracking and record the metric."""
        if self._start_time is None:
            return

        execution_time = (time.time() - self._start_time) * 1000  # Convert to milliseconds

        # Record error if exception occurred
        if exc_type is not None:
            self._error = f"{exc_type.__name__}: {str(exc_val)}"

        # Create and record metric
        metric = QueryMetric(
            query_type=self._query_type,
            execution_time_ms=execution_time,
            cache_hit=self._cache_hit,
            error=self._error,
        )

        self._monitor.record_metric(metric)

    def set_cache_hit(self, is_hit: bool) -> None:
        """
        Mark whether this query was a cache hit.

        Args:
            is_hit: True if query result came from cache
        """
        self._cache_hit = is_hit

    def set_error(self, error: str) -> None:
        """
        Record an error for this query.

        Args:
            error: Error description
        """
        self._error = error


# Global performance monitor instance
_performance_monitor: Optional[KGPerformanceMonitor] = None


def get_performance_monitor() -> KGPerformanceMonitor:
    """
    Get the global performance monitor instance.

    Returns:
        KGPerformanceMonitor instance
    """
    global _performance_monitor

    if _performance_monitor is None:
        _performance_monitor = KGPerformanceMonitor()

    return _performance_monitor


def initialize_performance_monitor(max_history: int = 10000) -> None:
    """
    Initialize the global performance monitor.

    Args:
        max_history: Maximum metrics to keep in memory
    """
    global _performance_monitor
    _performance_monitor = KGPerformanceMonitor(max_history)