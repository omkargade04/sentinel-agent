"""
Circuit Breaker Implementation

Production-grade circuit breaker pattern for protecting external dependencies
and implementing graceful degradation in context assembly pipeline.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Awaitable, List
from dataclasses import dataclass, field
from enum import Enum
import time

from .exceptions import CircuitBreakerOpenError, CircuitBreakerError

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"         # Failing, blocking calls
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerMetrics:
    """Metrics collected by circuit breaker."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    state_changed_time: datetime = field(default_factory=datetime.utcnow)

    @property
    def failure_rate(self) -> float:
        """Calculate current failure rate."""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests

    @property
    def success_rate(self) -> float:
        """Calculate current success rate."""
        return 1.0 - self.failure_rate

    def reset_failure_count(self) -> None:
        """Reset consecutive failure counter."""
        self.consecutive_failures = 0


class CircuitBreaker:
    """
    Production-grade circuit breaker with advanced features.

    Features:
    - Three states: CLOSED, OPEN, HALF_OPEN
    - Configurable failure thresholds and recovery timeouts
    - Exponential backoff for recovery attempts
    - Detailed metrics and monitoring
    - Support for async context manager pattern
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Exception = Exception,
        name: str = "DefaultCircuitBreaker"
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name

        # State management
        self._state = CircuitBreakerState.CLOSED
        self._state_lock = asyncio.Lock()

        # Metrics
        self.metrics = CircuitBreakerMetrics()

        # Configuration
        self._max_half_open_attempts = 3
        self._half_open_attempts = 0

        logger.info(
            f"Initialized CircuitBreaker '{name}': "
            f"failure_threshold={failure_threshold}, recovery_timeout={recovery_timeout}s"
        )

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get consecutive failure count."""
        return self.metrics.consecutive_failures

    @property
    def last_failure_time(self) -> Optional[datetime]:
        """Get timestamp of last failure."""
        return self.metrics.last_failure_time

    async def call(
        self,
        func: Callable[[], Awaitable[Any]],
        fallback: Optional[Callable[[], Awaitable[Any]]] = None,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            fallback: Optional fallback function if circuit is open
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result of func execution or fallback

        Raises:
            CircuitBreakerOpenError: If circuit is open and no fallback provided
        """
        async with self._state_lock:
            # Check if call should be allowed
            if not await self._should_allow_request():
                if fallback:
                    logger.info(f"Circuit breaker '{self.name}' open, using fallback")
                    return await fallback(*args, **kwargs)
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is open. "
                        f"Last failure: {self.metrics.last_failure_time}"
                    )

        # Execute the function
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time

            await self._record_success(execution_time)
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            await self._record_failure(e, execution_time)
            raise

    async def _should_allow_request(self) -> bool:
        """Determine if request should be allowed based on current state."""
        if self._state == CircuitBreakerState.CLOSED:
            return True

        if self._state == CircuitBreakerState.OPEN:
            # Check if recovery timeout has passed
            if self.metrics.last_failure_time:
                time_since_failure = datetime.utcnow() - self.metrics.last_failure_time
                if time_since_failure >= timedelta(seconds=self.recovery_timeout):
                    await self._transition_to_half_open()
                    return True

            return False

        if self._state == CircuitBreakerState.HALF_OPEN:
            # Allow limited requests to test recovery
            if self._half_open_attempts < self._max_half_open_attempts:
                return True

            return False

        return False

    async def _record_success(self, execution_time: float) -> None:
        """Record successful execution."""
        async with self._state_lock:
            self.metrics.total_requests += 1
            self.metrics.successful_requests += 1
            self.metrics.last_success_time = datetime.utcnow()

            # Reset failure count on success
            if self.metrics.consecutive_failures > 0:
                logger.info(
                    f"Circuit breaker '{self.name}' recorded success after "
                    f"{self.metrics.consecutive_failures} failures"
                )
                self.metrics.reset_failure_count()

            # State transitions
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_attempts += 1

                # Successful half-open requests indicate recovery
                if self._half_open_attempts >= self._max_half_open_attempts:
                    await self._transition_to_closed()

            logger.debug(
                f"Circuit breaker '{self.name}' success: "
                f"{execution_time:.3f}s, state={self._state.value}"
            )

    async def _record_failure(self, exception: Exception, execution_time: float) -> None:
        """Record failed execution."""
        async with self._state_lock:
            self.metrics.total_requests += 1
            self.metrics.failed_requests += 1
            self.metrics.consecutive_failures += 1
            self.metrics.last_failure_time = datetime.utcnow()

            logger.warning(
                f"Circuit breaker '{self.name}' failure: {exception} "
                f"({execution_time:.3f}s, {self.metrics.consecutive_failures} consecutive)"
            )

            # State transitions
            if self._state == CircuitBreakerState.CLOSED:
                if self.metrics.consecutive_failures >= self.failure_threshold:
                    await self._transition_to_open()

            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Failure during half-open immediately goes back to open
                await self._transition_to_open()

    async def _transition_to_open(self) -> None:
        """Transition circuit breaker to OPEN state."""
        if self._state != CircuitBreakerState.OPEN:
            logger.warning(
                f"Circuit breaker '{self.name}' opening: "
                f"{self.metrics.consecutive_failures} consecutive failures"
            )

            self._state = CircuitBreakerState.OPEN
            self.metrics.state_changed_time = datetime.utcnow()
            self._half_open_attempts = 0

    async def _transition_to_half_open(self) -> None:
        """Transition circuit breaker to HALF_OPEN state."""
        if self._state != CircuitBreakerState.HALF_OPEN:
            logger.info(
                f"Circuit breaker '{self.name}' half-open: "
                f"testing recovery after {self.recovery_timeout}s timeout"
            )

            self._state = CircuitBreakerState.HALF_OPEN
            self.metrics.state_changed_time = datetime.utcnow()
            self._half_open_attempts = 0

    async def _transition_to_closed(self) -> None:
        """Transition circuit breaker to CLOSED state."""
        if self._state != CircuitBreakerState.CLOSED:
            logger.info(
                f"Circuit breaker '{self.name}' closing: "
                f"service recovered after {self._half_open_attempts} successful tests"
            )

            self._state = CircuitBreakerState.CLOSED
            self.metrics.state_changed_time = datetime.utcnow()
            self._half_open_attempts = 0

    def can_execute(self) -> bool:
        """Check if circuit breaker allows execution (non-async)."""
        if self._state == CircuitBreakerState.CLOSED:
            return True

        if self._state == CircuitBreakerState.OPEN:
            # Check timeout without async
            if self.metrics.last_failure_time:
                time_since_failure = datetime.utcnow() - self.metrics.last_failure_time
                return time_since_failure >= timedelta(seconds=self.recovery_timeout)
            return False

        if self._state == CircuitBreakerState.HALF_OPEN:
            return self._half_open_attempts < self._max_half_open_attempts

        return False

    async def __aenter__(self):
        """Async context manager entry."""
        if not self.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is open"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if exc_type is None:
            # Success
            await self._record_success(0.0)
        else:
            # Failure
            await self._record_failure(exc_val or Exception("Unknown error"), 0.0)

        return False  # Don't suppress exceptions

    def force_open(self) -> None:
        """Manually force circuit breaker open (for testing/emergencies)."""
        logger.warning(f"Manually forcing circuit breaker '{self.name}' open")
        self._state = CircuitBreakerState.OPEN
        self.metrics.last_failure_time = datetime.utcnow()
        self.metrics.consecutive_failures = self.failure_threshold

    def force_close(self) -> None:
        """Manually force circuit breaker closed (for testing/recovery)."""
        logger.info(f"Manually forcing circuit breaker '{self.name}' closed")
        self._state = CircuitBreakerState.CLOSED
        self.metrics.reset_failure_count()
        self._half_open_attempts = 0

    def get_metrics(self) -> Dict[str, Any]:
        """Get detailed metrics for monitoring."""
        uptime = datetime.utcnow() - self.metrics.state_changed_time

        return {
            "name": self.name,
            "state": self._state.value,
            "total_requests": self.metrics.total_requests,
            "successful_requests": self.metrics.successful_requests,
            "failed_requests": self.metrics.failed_requests,
            "consecutive_failures": self.metrics.consecutive_failures,
            "failure_rate": self.metrics.failure_rate,
            "success_rate": self.metrics.success_rate,
            "last_failure_time": self.metrics.last_failure_time.isoformat() if self.metrics.last_failure_time else None,
            "last_success_time": self.metrics.last_success_time.isoformat() if self.metrics.last_success_time else None,
            "state_changed_time": self.metrics.state_changed_time.isoformat(),
            "time_in_current_state_seconds": uptime.total_seconds(),
            "half_open_attempts": self._half_open_attempts,
            "config": {
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "max_half_open_attempts": self._max_half_open_attempts
            }
        }

    def reset_metrics(self) -> None:
        """Reset all metrics (for testing)."""
        self.metrics = CircuitBreakerMetrics()
        self._half_open_attempts = 0

    def health_check(self) -> Dict[str, Any]:
        """Get health status for monitoring systems."""
        is_healthy = self._state == CircuitBreakerState.CLOSED

        health_status = "healthy" if is_healthy else "degraded"
        if self._state == CircuitBreakerState.OPEN:
            health_status = "unhealthy"

        return {
            "status": health_status,
            "state": self._state.value,
            "consecutive_failures": self.metrics.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "time_since_last_failure": (
                (datetime.utcnow() - self.metrics.last_failure_time).total_seconds()
                if self.metrics.last_failure_time else None
            ),
            "recovery_timeout_remaining": (
                max(0, self.recovery_timeout - (
                    datetime.utcnow() - self.metrics.last_failure_time
                ).total_seconds()) if self.metrics.last_failure_time and self._state == CircuitBreakerState.OPEN else 0
            )
        }


class MultiCircuitBreaker:
    """
    Manager for multiple circuit breakers with coordinated behavior.

    Useful for managing circuit breakers for different external services
    (Claude API, Neo4j, etc.) with unified monitoring and control.
    """

    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

        logger.info("Initialized MultiCircuitBreaker manager")

    def register_circuit_breaker(
        self,
        name: str,
        circuit_breaker: CircuitBreaker
    ) -> None:
        """Register a circuit breaker with the manager."""
        self.circuit_breakers[name] = circuit_breaker
        logger.info(f"Registered circuit breaker: {name}")

    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name."""
        return self.circuit_breakers.get(name)

    async def call_with_circuit_breaker(
        self,
        name: str,
        func: Callable[[], Awaitable[Any]],
        fallback: Optional[Callable[[], Awaitable[Any]]] = None,
        *args,
        **kwargs
    ) -> Any:
        """Execute function with named circuit breaker protection."""
        circuit_breaker = self.get_circuit_breaker(name)
        if not circuit_breaker:
            raise CircuitBreakerError(f"No circuit breaker registered with name: {name}")

        return await circuit_breaker.call(func, fallback, *args, **kwargs)

    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall health status of all circuit breakers."""
        if not self.circuit_breakers:
            return {
                "status": "unknown",
                "message": "No circuit breakers registered",
                "circuit_breakers": {}
            }

        circuit_statuses = {}
        healthy_count = 0
        degraded_count = 0
        unhealthy_count = 0

        for name, cb in self.circuit_breakers.items():
            health = cb.health_check()
            circuit_statuses[name] = health

            if health["status"] == "healthy":
                healthy_count += 1
            elif health["status"] == "degraded":
                degraded_count += 1
            else:
                unhealthy_count += 1

        # Determine overall status
        total_count = len(self.circuit_breakers)

        if unhealthy_count == 0 and degraded_count == 0:
            overall_status = "healthy"
        elif unhealthy_count == 0:
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        return {
            "status": overall_status,
            "summary": {
                "total": total_count,
                "healthy": healthy_count,
                "degraded": degraded_count,
                "unhealthy": unhealthy_count
            },
            "circuit_breakers": circuit_statuses
        }

    def get_aggregated_metrics(self) -> Dict[str, Any]:
        """Get aggregated metrics from all circuit breakers."""
        if not self.circuit_breakers:
            return {"message": "No circuit breakers registered"}

        total_requests = 0
        total_successful = 0
        total_failed = 0
        metrics_by_cb = {}

        for name, cb in self.circuit_breakers.items():
            metrics = cb.get_metrics()
            metrics_by_cb[name] = metrics

            total_requests += metrics["total_requests"]
            total_successful += metrics["successful_requests"]
            total_failed += metrics["failed_requests"]

        overall_failure_rate = total_failed / max(total_requests, 1)

        return {
            "aggregate": {
                "total_requests": total_requests,
                "successful_requests": total_successful,
                "failed_requests": total_failed,
                "overall_failure_rate": overall_failure_rate,
                "overall_success_rate": 1.0 - overall_failure_rate
            },
            "by_circuit_breaker": metrics_by_cb
        }

    def force_all_open(self) -> None:
        """Force all circuit breakers open (emergency shutdown)."""
        logger.warning("Forcing ALL circuit breakers open")
        for cb in self.circuit_breakers.values():
            cb.force_open()

    def force_all_closed(self) -> None:
        """Force all circuit breakers closed (emergency recovery)."""
        logger.warning("Forcing ALL circuit breakers closed")
        for cb in self.circuit_breakers.values():
            cb.force_close()

    def reset_all_metrics(self) -> None:
        """Reset metrics for all circuit breakers."""
        for cb in self.circuit_breakers.values():
            cb.reset_metrics()