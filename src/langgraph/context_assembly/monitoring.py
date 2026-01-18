"""
Monitoring and Observability for Context Assembly System

Production-grade monitoring with metrics collection, health checks,
distributed tracing, and operational dashboards.
"""

import time
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import json

# For production environments, these would be actual monitoring libraries
# from prometheus_client import Counter, Histogram, Gauge
# from opentelemetry import trace
# from datadog import statsd

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics that can be collected."""
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"
    TIMER = "timer"


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class MetricPoint:
    """Single metric data point."""
    name: str
    value: float
    timestamp: datetime
    tags: Dict[str, str] = field(default_factory=dict)
    metric_type: MetricType = MetricType.GAUGE


@dataclass
class Alert:
    """Alert definition and state."""
    name: str
    condition: str
    severity: AlertSeverity
    threshold: float
    current_value: Optional[float] = None
    triggered: bool = False
    triggered_at: Optional[datetime] = None
    message: str = ""


class MetricsCollector:
    """
    Centralized metrics collector for context assembly system.

    Collects performance metrics, error rates, cost tracking,
    and operational statistics for monitoring and alerting.
    """

    def __init__(self):
        self.metrics: List[MetricPoint] = []
        self.alerts: List[Alert] = []
        self.start_time = datetime.utcnow()

        # Initialize standard alerts
        self._setup_default_alerts()

    def record_counter(self, name: str, value: float = 1.0, tags: Dict[str, str] = None) -> None:
        """Record a counter metric."""
        self.metrics.append(MetricPoint(
            name=name,
            value=value,
            timestamp=datetime.utcnow(),
            tags=tags or {},
            metric_type=MetricType.COUNTER
        ))

    def record_histogram(self, name: str, value: float, tags: Dict[str, str] = None) -> None:
        """Record a histogram metric."""
        self.metrics.append(MetricPoint(
            name=name,
            value=value,
            timestamp=datetime.utcnow(),
            tags=tags or {},
            metric_type=MetricType.HISTOGRAM
        ))

    def record_gauge(self, name: str, value: float, tags: Dict[str, str] = None) -> None:
        """Record a gauge metric."""
        self.metrics.append(MetricPoint(
            name=name,
            value=value,
            timestamp=datetime.utcnow(),
            tags=tags or {},
            metric_type=MetricType.GAUGE
        ))

    def timer(self, name: str, tags: Dict[str, str] = None):
        """Context manager for timing operations."""
        return MetricTimer(self, name, tags or {})

    def get_metrics_summary(self, time_window_minutes: int = 60) -> Dict[str, Any]:
        """Get metrics summary for specified time window."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        recent_metrics = [m for m in self.metrics if m.timestamp >= cutoff_time]

        # Group metrics by name and type
        grouped_metrics = {}
        for metric in recent_metrics:
            key = f"{metric.name}:{metric.metric_type.value}"
            if key not in grouped_metrics:
                grouped_metrics[key] = []
            grouped_metrics[key].append(metric.value)

        # Calculate statistics
        summary = {}
        for key, values in grouped_metrics.items():
            metric_name, metric_type = key.split(':')
            summary[metric_name] = {
                "type": metric_type,
                "count": len(values),
                "sum": sum(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "latest": values[-1] if values else 0
            }

        return {
            "time_window_minutes": time_window_minutes,
            "metrics": summary,
            "total_data_points": len(recent_metrics)
        }

    def _setup_default_alerts(self) -> None:
        """Setup default alert conditions."""
        self.alerts.extend([
            Alert(
                name="high_error_rate",
                condition="error_rate > threshold",
                severity=AlertSeverity.ERROR,
                threshold=0.05,  # 5% error rate
                message="Context assembly error rate is high"
            ),
            Alert(
                name="cost_budget_warning",
                condition="cost_utilization > threshold",
                severity=AlertSeverity.WARNING,
                threshold=0.8,  # 80% of budget
                message="Context assembly cost approaching budget limit"
            ),
            Alert(
                name="high_latency",
                condition="avg_latency > threshold",
                severity=AlertSeverity.WARNING,
                threshold=30.0,  # 30 seconds
                message="Context assembly latency is high"
            ),
            Alert(
                name="circuit_breaker_open",
                condition="circuit_breaker_state == 'open'",
                severity=AlertSeverity.CRITICAL,
                threshold=1.0,
                message="Circuit breaker is open - service degraded"
            )
        ])

    def check_alerts(self, metrics_data: Dict[str, Any]) -> List[Alert]:
        """Check alert conditions and return triggered alerts."""
        triggered_alerts = []

        for alert in self.alerts:
            try:
                should_trigger = self._evaluate_alert_condition(alert, metrics_data)

                if should_trigger and not alert.triggered:
                    # New alert triggered
                    alert.triggered = True
                    alert.triggered_at = datetime.utcnow()
                    triggered_alerts.append(alert)
                    logger.error(f"ALERT TRIGGERED: {alert.name} - {alert.message}")

                elif not should_trigger and alert.triggered:
                    # Alert resolved
                    alert.triggered = False
                    alert.triggered_at = None
                    logger.info(f"ALERT RESOLVED: {alert.name}")

            except Exception as e:
                logger.warning(f"Failed to evaluate alert {alert.name}: {e}")

        return triggered_alerts

    def _evaluate_alert_condition(self, alert: Alert, metrics_data: Dict[str, Any]) -> bool:
        """Evaluate whether alert condition is met."""
        # This is a simplified implementation
        # In production, you'd use a proper expression evaluator

        if alert.name == "high_error_rate":
            error_count = metrics_data.get("context_assembly_errors", {}).get("sum", 0)
            total_count = metrics_data.get("context_assembly_requests", {}).get("sum", 1)
            error_rate = error_count / total_count
            alert.current_value = error_rate
            return error_rate > alert.threshold

        elif alert.name == "cost_budget_warning":
            current_cost = metrics_data.get("llm_cost_usd", {}).get("latest", 0)
            max_cost = 0.30  # Default budget
            cost_utilization = current_cost / max_cost
            alert.current_value = cost_utilization
            return cost_utilization > alert.threshold

        elif alert.name == "high_latency":
            avg_latency = metrics_data.get("assembly_duration_seconds", {}).get("avg", 0)
            alert.current_value = avg_latency
            return avg_latency > alert.threshold

        return False


class MetricTimer:
    """Context manager for timing operations."""

    def __init__(self, collector: MetricsCollector, name: str, tags: Dict[str, str]):
        self.collector = collector
        self.name = name
        self.tags = tags
        self.start_time: Optional[float] = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            self.collector.record_histogram(self.name, duration, self.tags)


class ContextAssemblyMonitor:
    """
    Specialized monitor for context assembly operations.

    Tracks assembly-specific metrics like context quality,
    LLM usage, truncation rates, and workflow performance.
    """

    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics_collector = metrics_collector
        self.operation_id: Optional[str] = None

    def start_assembly_operation(self, operation_id: str, metadata: Dict[str, Any] = None) -> None:
        """Start monitoring an assembly operation."""
        self.operation_id = operation_id

        tags = {
            "operation_id": operation_id,
            "repo": metadata.get("github_repo_name", "unknown") if metadata else "unknown",
            "pr_number": str(metadata.get("pr_number", 0)) if metadata else "0"
        }

        self.metrics_collector.record_counter("context_assembly_started", 1.0, tags)
        logger.info(f"Started monitoring context assembly operation: {operation_id}")

    def record_workflow_stage(self, stage_name: str, duration_seconds: float, success: bool = True) -> None:
        """Record workflow stage completion."""
        if not self.operation_id:
            logger.warning("No active operation for workflow stage recording")
            return

        tags = {
            "operation_id": self.operation_id,
            "stage": stage_name,
            "success": str(success)
        }

        self.metrics_collector.record_histogram("workflow_stage_duration", duration_seconds, tags)
        self.metrics_collector.record_counter("workflow_stage_completed", 1.0, tags)

        if not success:
            self.metrics_collector.record_counter("workflow_stage_errors", 1.0, tags)

    def record_llm_usage(self, input_tokens: int, output_tokens: int, cost_usd: float, provider: str = "claude") -> None:
        """Record LLM API usage metrics."""
        tags = {
            "operation_id": self.operation_id or "unknown",
            "provider": provider
        }

        self.metrics_collector.record_counter("llm_requests", 1.0, tags)
        self.metrics_collector.record_histogram("llm_input_tokens", input_tokens, tags)
        self.metrics_collector.record_histogram("llm_output_tokens", output_tokens, tags)
        self.metrics_collector.record_histogram("llm_cost_usd", cost_usd, tags)
        self.metrics_collector.record_gauge("llm_cost_total", cost_usd, tags)

    def record_context_quality(
        self,
        total_items: int,
        relevant_items: int,
        truncated_items: int,
        total_characters: int,
        avg_relevance_score: float
    ) -> None:
        """Record context quality metrics."""
        tags = {"operation_id": self.operation_id or "unknown"}

        self.metrics_collector.record_gauge("context_total_items", total_items, tags)
        self.metrics_collector.record_gauge("context_relevant_items", relevant_items, tags)
        self.metrics_collector.record_gauge("context_truncated_items", truncated_items, tags)
        self.metrics_collector.record_gauge("context_total_characters", total_characters, tags)
        self.metrics_collector.record_gauge("context_avg_relevance", avg_relevance_score, tags)

        # Calculate quality ratios
        relevance_ratio = relevant_items / max(total_items, 1)
        truncation_ratio = truncated_items / max(total_items, 1)

        self.metrics_collector.record_gauge("context_relevance_ratio", relevance_ratio, tags)
        self.metrics_collector.record_gauge("context_truncation_ratio", truncation_ratio, tags)

    def record_resource_usage(self, cpu_percent: float, memory_mb: float, processing_time: float) -> None:
        """Record resource usage metrics."""
        tags = {"operation_id": self.operation_id or "unknown"}

        self.metrics_collector.record_gauge("cpu_usage_percent", cpu_percent, tags)
        self.metrics_collector.record_gauge("memory_usage_mb", memory_mb, tags)
        self.metrics_collector.record_histogram("processing_time_seconds", processing_time, tags)

    def complete_assembly_operation(self, success: bool, total_duration: float, error_type: str = None) -> None:
        """Complete monitoring of an assembly operation."""
        if not self.operation_id:
            logger.warning("No active operation to complete")
            return

        tags = {
            "operation_id": self.operation_id,
            "success": str(success)
        }

        if error_type:
            tags["error_type"] = error_type

        self.metrics_collector.record_histogram("assembly_duration_seconds", total_duration, tags)
        self.metrics_collector.record_counter("context_assembly_completed", 1.0, tags)

        if success:
            self.metrics_collector.record_counter("context_assembly_success", 1.0, tags)
        else:
            self.metrics_collector.record_counter("context_assembly_errors", 1.0, tags)

        logger.info(f"Completed monitoring context assembly operation: {self.operation_id}")
        self.operation_id = None


class HealthCheckManager:
    """
    Comprehensive health check manager for context assembly system.

    Performs health checks on all system components and provides
    detailed health status for monitoring and alerting.
    """

    def __init__(self):
        self.health_checks: Dict[str, Callable] = {}
        self.last_check_results: Dict[str, Dict] = {}
        self.check_history: List[Dict] = []

    def register_health_check(self, name: str, check_function: Callable) -> None:
        """Register a health check function."""
        self.health_checks[name] = check_function
        logger.info(f"Registered health check: {name}")

    async def run_all_health_checks(self) -> Dict[str, Any]:
        """Run all registered health checks."""
        results = {}
        overall_status = "healthy"
        check_timestamp = datetime.utcnow()

        for name, check_function in self.health_checks.items():
            try:
                if asyncio.iscoroutinefunction(check_function):
                    result = await check_function()
                else:
                    result = check_function()

                results[name] = result
                self.last_check_results[name] = result

                # Determine overall status
                if result.get("status") == "unhealthy":
                    overall_status = "unhealthy"
                elif result.get("status") == "degraded" and overall_status == "healthy":
                    overall_status = "degraded"

            except Exception as e:
                error_result = {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": check_timestamp.isoformat()
                }
                results[name] = error_result
                self.last_check_results[name] = error_result
                overall_status = "unhealthy"

                logger.error(f"Health check failed for {name}: {e}")

        # Store in history
        health_summary = {
            "timestamp": check_timestamp,
            "overall_status": overall_status,
            "checks": results,
            "check_count": len(results),
            "healthy_count": len([r for r in results.values() if r.get("status") == "healthy"]),
            "degraded_count": len([r for r in results.values() if r.get("status") == "degraded"]),
            "unhealthy_count": len([r for r in results.values() if r.get("status") == "unhealthy"])
        }

        self.check_history.append(health_summary)

        # Keep only recent history (last 100 checks)
        if len(self.check_history) > 100:
            self.check_history = self.check_history[-100:]

        return health_summary

    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status without running checks."""
        if not self.last_check_results:
            return {"status": "unknown", "message": "No health checks have been run"}

        overall_status = "healthy"
        for result in self.last_check_results.values():
            if result.get("status") == "unhealthy":
                overall_status = "unhealthy"
                break
            elif result.get("status") == "degraded":
                overall_status = "degraded"

        return {
            "status": overall_status,
            "checks": self.last_check_results,
            "last_check_time": max(
                datetime.fromisoformat(result.get("timestamp", "1970-01-01T00:00:00"))
                for result in self.last_check_results.values()
                if result.get("timestamp")
            ).isoformat() if self.last_check_results else None
        }


class OperationalDashboard:
    """
    Operational dashboard for context assembly system.

    Provides real-time monitoring dashboard with key metrics,
    alerts, and system health status.
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector,
        health_check_manager: HealthCheckManager
    ):
        self.metrics_collector = metrics_collector
        self.health_check_manager = health_check_manager
        self.dashboard_start_time = datetime.utcnow()

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get complete dashboard data."""
        # Get recent metrics (last hour)
        metrics_summary = self.metrics_collector.get_metrics_summary(time_window_minutes=60)

        # Get health status
        health_status = self.health_check_manager.get_health_status()

        # Check for active alerts
        active_alerts = [alert for alert in self.metrics_collector.alerts if alert.triggered]

        # Calculate uptime
        uptime_seconds = (datetime.utcnow() - self.dashboard_start_time).total_seconds()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": uptime_seconds,
            "system_health": health_status,
            "metrics_summary": metrics_summary,
            "active_alerts": [
                {
                    "name": alert.name,
                    "severity": alert.severity.value,
                    "message": alert.message,
                    "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
                    "current_value": alert.current_value
                }
                for alert in active_alerts
            ],
            "key_performance_indicators": self._calculate_kpis(metrics_summary),
        }

    def _calculate_kpis(self, metrics_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate key performance indicators."""
        metrics = metrics_summary.get("metrics", {})

        # Success rate
        success_count = metrics.get("context_assembly_success", {}).get("sum", 0)
        error_count = metrics.get("context_assembly_errors", {}).get("sum", 0)
        total_requests = success_count + error_count
        success_rate = success_count / max(total_requests, 1) * 100

        # Average processing time
        avg_duration = metrics.get("assembly_duration_seconds", {}).get("avg", 0)

        # Cost efficiency
        total_cost = metrics.get("llm_cost_usd", {}).get("sum", 0)
        cost_per_request = total_cost / max(total_requests, 1)

        # Context quality
        avg_relevance = metrics.get("context_avg_relevance", {}).get("avg", 0)
        avg_truncation_ratio = metrics.get("context_truncation_ratio", {}).get("avg", 0)

        return {
            "success_rate_percent": round(success_rate, 2),
            "avg_processing_time_seconds": round(avg_duration, 2),
            "total_requests": int(total_requests),
            "total_cost_usd": round(total_cost, 4),
            "cost_per_request_usd": round(cost_per_request, 4),
            "avg_context_relevance": round(avg_relevance, 3),
            "avg_truncation_ratio": round(avg_truncation_ratio, 3)
        }

    def export_metrics_json(self, filepath: str) -> None:
        """Export dashboard data to JSON file."""
        dashboard_data = self.get_dashboard_data()

        try:
            with open(filepath, 'w') as f:
                json.dump(dashboard_data, f, indent=2, default=str)
            logger.info(f"Dashboard data exported to {filepath}")
        except Exception as e:
            logger.error(f"Failed to export dashboard data: {e}")

    def get_health_summary_text(self) -> str:
        """Get text summary of system health."""
        health_status = self.health_check_manager.get_health_status()
        dashboard_data = self.get_dashboard_data()

        status_emoji = {
            "healthy": "✅",
            "degraded": "⚠️",
            "unhealthy": "❌",
            "unknown": "❓"
        }

        kpis = dashboard_data["key_performance_indicators"]
        active_alerts = dashboard_data["active_alerts"]

        summary = f"""
Context Assembly System Health Report
=====================================

Overall Status: {status_emoji.get(health_status['status'], '❓')} {health_status['status'].upper()}

Key Metrics (Last Hour):
• Success Rate: {kpis['success_rate_percent']}%
• Avg Processing Time: {kpis['avg_processing_time_seconds']}s
• Total Requests: {kpis['total_requests']}
• Total Cost: ${kpis['total_cost_usd']}
• Avg Context Relevance: {kpis['avg_context_relevance']:.2f}

Active Alerts: {len(active_alerts)}
{chr(10).join(f"  • {alert['severity'].upper()}: {alert['name']} - {alert['message']}" for alert in active_alerts)}

System Uptime: {dashboard_data['uptime_seconds']:.0f} seconds
Report Time: {dashboard_data['timestamp']}
"""
        return summary.strip()


# Factory function for setting up monitoring
def create_context_assembly_monitoring() -> tuple[MetricsCollector, ContextAssemblyMonitor, HealthCheckManager, OperationalDashboard]:
    """Create complete monitoring setup for context assembly system."""

    # Initialize core components
    metrics_collector = MetricsCollector()
    assembly_monitor = ContextAssemblyMonitor(metrics_collector)
    health_check_manager = HealthCheckManager()
    dashboard = OperationalDashboard(metrics_collector, health_check_manager)

    # Register standard health checks
    def basic_health_check() -> Dict[str, Any]:
        """Basic system health check."""
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "component": "context_assembly_monitoring"
        }

    health_check_manager.register_health_check("basic", basic_health_check)

    logger.info("Context assembly monitoring system initialized")

    return metrics_collector, assembly_monitor, health_check_manager, dashboard